# CROWDGUARD real-time architecture

This document describes the live monitoring pipeline on branch `feature/crowdguard-realtime-ux`: how a camera frame becomes
a person on the top-down map, a cell of free or congested floor, an alert and a route recommendation. It also records what
was broken before, what was measured on real hardware, and what has not been verified.

Code lives in `backend/app/crowdguard/` (`camera_sources.py`, `live_monitor.py`, `site_model.py`, `occupancy.py`,
`guidance.py`, `live_alerts.py`), the `live_*` operations of the `crowd` engine (`backend/app/engines/crowd/engine.py`), the
REST and WebSocket routes in `backend/app/api/crowdguard.py`, and the frontend under `frontend/src/live`, `frontend/src/map`
and `frontend/src/screens`. Tests: `backend/tests/test_crowdguard_live.py` (24 tests).

---

## 1. What was broken (diagnosis on `main` at 3eddcfd)

The pipeline was inspected end to end before anything was changed.

| Stage | What `main` did | Consequence |
|---|---|---|
| Camera input | No code opened a camera device. `cv2.VideoCapture` was only ever called with a file path (`media_analysis.py:115`, `pipeline.py:320`). | There was no live input at all. "Live monitoring" meant uploading a file. |
| Recorded video | Upload, then a background job; the browser polled `/media/jobs/{id}` every 700 ms until the job finished, then showed key frames. | Results arrived after the whole clip was processed, not as it played. |
| "Live" heatmap | The browser ran `setInterval` and called `POST /simulation/step`. Each response carried five rendered views as base64 JPEGs (`render_bundle(max_width=560)`). | It was the synthetic scene, advanced by HTTP polling, with large payloads and no sequence numbers. Throughput was bounded by request round trips. |
| Units | Peak and mean density were always shown as people per m², including under the default calibration, which is assumed rather than measured. | Units were fabricated for any real camera. |
| Missing feed | No live feed existed, so there was no notion of "unobserved" floor in the live view. | An absent camera could not be distinguished from an empty area. |

The fix keeps the existing YOLO detector (`crowd_detection.py`), the existing ByteTrack wrapper (`crowd_tracking.py`), and
the VCIE calibration and Kalman tracker (`perspective.py`, `tracking.py`). It adds real sources, a threaded pipeline with
latest-frame priority, a WebSocket transport, a metric site model, an occupancy grid and a route planner.

---

## 2. Pipeline

```
 camera / stream / recording / simulation
        │  capture thread: VideoCapture (CAP_DSHOW or CAP_MSMF on Windows, CAP_FFMPEG for RTSP), BUFFERSIZE=1
        ▼
 one-slot "latest frame" buffer ──── a newer frame replaces an unprocessed one (counted as "skipped")
        │  processing thread (never the FastAPI event loop)
        ▼
 YOLO person detection (local weights, conf ≥ 0.3)          synthetic source: ground-truth boxes instead
        ▼
 ByteTrack identities (Ultralytics BYTETracker)  →  confirmed tracks only
        ▼
 ground point = bottom-centre of the box
        ▼
 homography (VCIE CameraCalibrationEngine) → site metres;  Kalman filter on the ground plane (velocity, heading)
        ▼
 Gaussian KDE density  →  occupancy grid: available / occupied / congested / blocked / unknown
        ▼
 zone statistics  →  alerts (de-duplicated, cooldown)  →  A* route to the best usable exit (hysteresis)
        ▼
 snapshot (JSON, sequence number, capture timestamp)  →  per-client one-slot mailbox  →  WebSocket
        ▼
 browser: newest snapshot per animation frame → canvas layers + SVG map
```

### Threads and back-pressure

* **Capture thread.** Reads as fast as the source delivers and writes into a single slot. It never queues.
* **Processing thread.** Takes whatever is in the slot. If the slot was overwritten before it was processed, `skipped`
  increases. This is the latest-frame policy: the system falls behind by dropping frames, never by building a backlog.
* **Rate cap.** `max_fps` (default 12, range 1–30, set per start) limits analysis to keep a laptop responsive. Uncapped,
  the webcam ran at the camera's own rate (section 9).
* **Subscribers.** Each WebSocket client has one slot per message type (`status`, `snapshot`, `frame`). The processing thread
  fills them with `loop.call_soon_threadsafe`. A slow client therefore only ever receives the newest message, never a queue.
* **Stale data.** If no frame arrives for 2 s, a snapshot is published with every cell `unknown` and no route. A missing feed
  is never shown as empty floor.

---

## 3. Sources

| Kind | Label shown | Marked live? | Notes |
|---|---|---|---|
| `webcam` | `Camera N (W×H)` | yes, the only kind that is | Requests 1280×720. Discovery probes indices and reports `available`, `no_frames` (opens but returns nothing: in use or blocked by privacy settings) or `in_use_by_crowdguard`. |
| `stream` | host and path; credentials removed | yes | RTSP or HTTP via FFmpeg. `INVALID_STREAM` for a malformed URL, `STREAM_UNAVAILABLE` when it cannot be opened. |
| `file` | `Recording: name` | **no** | Uploaded or the bundled test clip. Paced at its own frame rate and looped. |
| `synthetic` | `Simulation: scenario` | **no** | VCIE pedestrian simulation rendered through its own exact camera. Boxes come from ground truth; the detector is reported as `synthetic ground truth`. |

Errors are specific: `CAMERA_UNAVAILABLE` (could not be opened: disconnected, in use, or blocked by OS privacy settings),
`NO_FRAMES`, `INVALID_STREAM`, `STREAM_UNAVAILABLE`, `PROCESSING_FAILED`. The API returns 409 for device conflicts.

**Disconnection.** Live sources reconnect with back-off from 1 s to 5 s. The first failure raises a critical
`camera_disconnected` alert and the area becomes unknown. Recovery raises `camera_reconnected`. Recordings and the simulation
do not reconnect: a recording that cannot be read ends with status `ended`.

**Slow camera.** A live camera delivering fewer than 3 frames per second after 6 s raises `camera_slow`.

---

## 4. Detection and tracking

* **Model.** YOLOv8n, loaded once per process. The weights search order is: the configured path, `CROWDGUARD_YOLO_WEIGHTS`,
  `backend/models/`, the repository root (`yolov8n.pt` ships there) and the home directory. `YOLO_OFFLINE=true` is set before
  import, so nothing is downloaded. A test inference runs at start-up and the result is reported (`verified`). Without
  weights the detector falls back to OpenCV HOG and says so on the Settings screen.
* **Device.** CUDA when `torch.cuda.is_available()`, otherwise CPU. The machine used for the measurements has no CUDA, so the
  GPU path has not been exercised.
* **Identity.** ByteTrack assigns the identity in image space. Only confirmed tracks continue. Their foot points are passed
  to the VCIE `MultiObjectTracker` with `external_ids`, so the ground-plane Kalman filter keeps the ByteTrack number. There is
  one detector and one tracker; nothing was duplicated.
* **Per track** the snapshot carries: `id`, `box` (normalised), `conf`, `foot_px`, `ground` (metres), `vel`, `speed` (m/s),
  `heading`, `last_seen`, `seen_ago_s`, `predicted`, `uncertainty_m` and `in_view`.
* **Occlusion.** A track not detected in the current frame is kept for up to 2 s as `predicted` ("estimated" in the UI). Its
  weight in the density falls from 0.7 to 0, and its position uncertainty grows by 0.3 m per second unseen.
* **Uncertainty.** `uncertainty_m` is the ground distance produced by a ±6 % error in box height at the foot point. It is
  perspective-aware: people far from the camera are less certain. The minimum is 0.15 m and the maximum 5 m.

---

## 5. Coordinate systems and calibration

| System | Units | Origin and axes | Used for |
|---|---|---|---|
| Image | pixels of the analysed frame | top-left, x right, y down | detection boxes, foot points, calibration clicks |
| Normalised box | 0–1 | as image | overlay on the preview frame (sent at a different size) |
| VCIE canvas | 800 × 600 units | top-left of the site | the existing `CameraCalibrationEngine` homography |
| Site | metres | top-left corner of the site, x across, y in depth | grid, zones, obstacles, exits, routes, speeds |

The homography maps four image points to the canvas corners. Site metres are `x = u · W / 800`, `y = v · H / 600`. The
homogeneous sign is fixed from a reference point (the quad centre must map to the canvas centre). Without that fix, a
negative overall scale put every person behind the camera.

**Assumed calibration.** Before an operator calibrates a camera, the floor quad is a default trapezoid (top edge at 42 % of
the frame height from 30 % to 70 % of the width, bottom edge at 96 % from 3 % to 97 %). It is labelled *assumed (not
measured)*. In this state all densities are a **relative index**, where 1.0 means the congestion threshold, and the map's
scale bar reads *assumed scale*.

**Measured calibration.** On **Live camera**, the operator clicks the four corners of a floor rectangle in order (far left,
far right, near right, near left), enters its real width and depth, and confirms that they were measured. Only then are
densities shown in people per m² (`metric: true`). The calibration is stored per source (`settings: crowdguard.calibrations`),
and the site is rescaled to the measured size. The simulation is labelled *simulated geometry (exact)* and is metric by
construction.

---

## 6. Occupancy grid (where people are not)

The site is a configurable grid (default 24 × 18 m, 0.75 m cells). It is edited on **Venue map → Monitored area layout**:
walkable outline, obstacles, zones (optionally restricted) and exits.

* **Density.** Gaussian kernel density of the tracked ground positions. Each person's kernel width is
  `max(kde_sigma_m, uncertainty_m)`, so uncertain positions spread out instead of producing sharp false peaks. The density
  integrates to the number of people (tested).
* **Cell state**, in order of precedence:
  * **blocked**: an obstacle, outside the walkable outline, or a restricted zone;
  * **unknown**: not visible to the calibrated camera, or the feed is down or stale;
  * **congested**: density ≥ `congested_density` (default 2.0 p/m²);
  * **occupied**: density ≥ `occupied_density` (default 0.5 p/m²) or a person stands in the cell;
  * **available**: everything else that is observed and walkable.
* **Free area** per cell is the cell area minus about 0.5 m² per person, and zero for blocked or unknown cells.
  The summary reports available, occupied, congested, blocked and unknown square metres, usable free floor, and the
  fraction of the walkable area that is observed.
* **Unknown is never empty.** Unknown cells are drawn hatched grey, contribute no free space, and cost extra to route through.
* **Zones** report population, capacity (configured, or 2 p/m² × area), occupancy %, band (normal, elevated, high, critical,
  unknown), mean speed, visible fraction, and density in p/m² only when the calibration is metric.

---

## 7. Route guidance

* **Graph.** NetworkX, an 8-connected grid of walkable cells. Diagonal moves may not cut the corner of a blocked cell.
  Restricted zones are blocked cells, so a route can never pass through one.
* **Cost** of entering a cell: `length × (1 + 3 × min(index, 3))`, plus 25 m for an unknown cell. Congested cells are excluded.
  Only if no exit is reachable without them is a second pass allowed, with a 200 m penalty per congested cell, and the
  recommendation says so.
* **Exit usability.** An exit or emergency exit is unusable if an operator marks it unavailable, if no walkable cell reaches it,
  or if more than half the cells within 1.5 m of it are congested. The software never closes an exit, and an emergency exit
  can only be marked unavailable by a person.
* **Search.** A* (`astar_path`) from the origin to every usable exit; the cheapest wins. A distance-only "naive" path to the
  nearest exit is computed alongside. The explanation says how many congested cells the direct way would cross, and why each
  rejected exit was not used.
* **Origin.** Either the busiest zone (automatic) or a point the operator picks on the map.
* **Hysteresis.** The current route is kept unless it becomes invalid, or a different exit is at least 15 % cheaper for 3
  consecutive updates and the current one has been held for at least 5 s. A switch raises `route_changed`.
* **No live observation, no route.** If every cell is unknown or blocked, guidance is unavailable and the UI says why.
* **Advisory only.** Every recommendation is labelled as advice for an organiser to approve. Nothing is broadcast to the public.

---

## 8. Alerts and transport

### Alerts

`AlertManager` keys each condition. While a condition holds, the alert is updated rather than raised again, and it escalates
when its severity rises. It clears after the condition has been false for 4 s, and the same key cannot raise again for 30 s
unless the severity is higher. Each alert has a timestamp, location, severity, observation and recommended action.

| Kind | Condition | Severity |
|---|---|---|
| `zone_capacity_exceeded` | occupancy ≥ 100 % | critical |
| `zone_near_capacity` | 85–99 % | high |
| `rapid_accumulation` | rise of ≥ max(3, 25 % of capacity) within 15 s | high |
| `flow_slowed` | ≥ 3 people and mean speed < 0.3 m/s | medium |
| `corridor_congestion` | congested floor ≥ 2 cells (high from 8 m²) | medium or high |
| `exit_unavailable` | an exit is unusable (section 7) | high; critical for an emergency exit |
| `detection_degraded` | mean confidence < 0.4 over ≥ 10 detections, or > 20 % failed frames | medium |
| `camera_slow` | a live camera delivers < 3 fps | medium |
| `camera_disconnected` / `camera_reconnected` | feed lost or recovered | critical / info |
| `route_changed` | the recommended exit changed | medium |

### WebSocket

`GET /api/crowdguard/live/ws?frames=0|1`. Messages are JSON with a `type`:

* `status`: the monitor state (`idle`, `starting`, `running`, `disconnected`, `ended`, `error`; snapshots also report `stale`), source, statistics, calibration
  and error. Sent on connect and on every state change.
* `snapshot`: sent for each analysed frame. It contains `seq`, `frame` (index, `captured_at`, size), `source`, `tracks`, `grid`
  (rows, cols, state string, values, unit, free area), `space` summary, `zones`, `route`, `alerts`, `new_alerts`,
  `calibration`, `stats` (fps, capture fps, processing ms, capture-to-result ms, skipped, reconnects) and the detector and
  tracker names. With 45 simulated people a snapshot is about 23 KB.
* `frame`: a JPEG preview (640 px wide, quality 62) at most 4 times a second, only for clients that asked with `frames=1`
  (the Live camera screen). The map never needs the image.

A new client receives the newest snapshot immediately. Switching or stopping a source clears it, so a client never receives
the previous source's picture. The browser reconnects with back-off from 0.5 s to 5 s and applies at most one snapshot per
animation frame.

REST (all under `/api/crowdguard`): `GET live/status`, `GET live/cameras`, `POST live/start`, `POST live/stop`,
`GET|PUT live/site`, `POST live/calibration`, `POST live/origin`, `POST live/portals`, `GET live/alerts`,
`GET|POST live/recordings`, `POST live/recordings/sample`. Writes go through the engine policy gate and are audited.

---

## 9. Measured performance

Measured on 2026-11-19 on the development laptop: 13th Gen Intel Core i7-13700HX, 16 GB RAM, CPU inference only (no CUDA),
Windows 11, the laptop's webcam, YOLOv8n. Each run was measured through the real API and WebSocket, after a 3 s warm-up. Latency is from
frame capture to the snapshot arriving at a WebSocket client on the same machine.

| Source | Analysed fps | Camera fps | Processing per frame (median / p95) | Capture → client (median / p95 / max) | Detections per frame (median, range) |
|---|---|---|---|---|---|
| Webcam 1280×720, cap 12 fps | 12.0 | 30.0 | 26 / 34 ms | 46 / 62 / 75 ms | 4 (1–7) |
| Webcam 1280×720, uncapped (`max_fps` 30) | 29.2 (min 28.4) | 30.0 | 29 ms | 46 / 61 ms | not recorded |
| Recording (bundled test clip, 640×678) | 12.0 | 15.2 | 33 / 50 ms | 71 / 101 / 117 ms | 3 (2–5) |
| Simulation (`surge_gate`, 60 people) | 9.9 | 9.9 (its native rate) | 19 / 24 ms | 24 / 34 / 36 ms | 60 (ground truth) |

Identity persistence (webcam, cap 12, 22 s of snapshots): 24 distinct track ids, and the longest-lived id was present in 245
of 265 snapshots. The raw measurement output is reproduced in [`CROWDGUARD_TEST_RESULTS.md`](CROWDGUARD_TEST_RESULTS.md#real-time-pipeline-measurements).

**What these numbers do not show.** The webcam frames were not viewed, for privacy, so whether every detection was a real
person, and how many people were present, was not checked. The detection counts are not accuracy figures. Density in these
runs is a relative index, because the webcam was not calibrated with measured distances.

---

## 10. Verified and not verified

| Behaviour | Status |
|---|---|
| Webcam discovery, open, continuous analysis, ByteTrack identity across frames | Verified on the real webcam (above). |
| Latest-frame policy (no backlog) | Verified: `skipped` grows while capture exceeds analysis; unit test `test_latest_frame_wins_no_backlog`. |
| Camera disconnect → unknown area → reconnect | Unit test with a fake source that stops and recovers. **Not** tested by physically unplugging a camera. |
| Camera already in use | On this machine Windows let a second process share the webcam: CROWDGUARD started but received about 1 frame per second. The `camera_slow` alert was added for that case. The `CAMERA_UNAVAILABLE` and `no_frames` paths are covered by unit tests with a fake `VideoCapture`, not by a real exclusive lock. |
| Camera permission denied (Windows privacy setting) | **Not** reproduced. It surfaces as `CAMERA_UNAVAILABLE` or `no_frames`, and the message names privacy settings as a cause. |
| RTSP | URL validation and credential hiding are unit-tested. **Not** tested against a real network camera. |
| GPU | **Not** tested (no CUDA on this machine). |
| Metric densities from a measured calibration | API rules are unit-tested (metric needs confirmed measurements). Not validated against people counted on a measured floor. |

---

## 11. Limitations

* One camera per monitored area. Several cameras over one site would need ground-plane fusion, which is not built.
* The foot point is the bottom of the box. Partly occluded people (box cut off) are placed too far away. The uncertainty
  model widens their kernel but does not correct the position.
* YOLOv8n on CPU misses small or heavily occluded people in dense crowds, so counts in dense scenes are lower bounds.
* The homography assumes a flat floor. Stairs and ramps are wrong.
* `occupied_density` and `congested_density` defaults (0.5 and 2.0 p/m²) are configurable planning values, not a safety standard.
* Alerts and routes are advisory and need human confirmation. CROWDGUARD does not certify that an event is safe.
* There is no authentication. The operator name and role are declared by the browser (OMNIFORGE identity headers).
