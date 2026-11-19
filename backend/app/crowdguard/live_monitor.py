"""Real-time monitoring: capture → detect → track → project → occupancy → guidance → alerts → WebSocket.

Threads (never the FastAPI event loop):
  * capture thread  – reads the source as fast as it delivers and keeps ONLY the newest frame
                      (a one-slot buffer: old frames are overwritten and counted as skipped, so there
                      is never a growing backlog and the map always shows the latest moment);
                      detects disconnection and reconnects live cameras with back-off.
  * process thread  – takes the newest frame, runs the single detector (crowd_detection: YOLO / HOG),
                      ByteTrack identities (crowd_tracking), ground-plane Kalman kinematics (tracking),
                      the site homography, occupancy and guidance, then publishes one JSON snapshot.

Subscribers (WebSocket clients) hold one slot per message type, so a slow client simply receives the
newest snapshot when it is ready; nothing queues up.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .camera_sources import Frame, FrameSource, SourceError, SyntheticSource
from .crowd_detection import Detection
from .guidance import GuidanceController, RoutePlanner
from .live_alerts import AlertManager
from .occupancy import GroundPerson, compute_occupancy
from .site_model import GroundProjector, LiveCalibration, SiteMasks, SiteModel, default_site, zone_centroid

log = logging.getLogger("crowdguard.live")
STALE_AFTER_S = 2.0
FRAME_PREVIEW_INTERVAL_S = 0.25
GUIDANCE_INTERVAL_S = 0.5


@dataclass
class Subscriber:
    loop: asyncio.AbstractEventLoop
    frames: bool
    event: asyncio.Event = field(default_factory=asyncio.Event)
    slots: dict[str, str] = field(default_factory=dict)

    def offer(self, kind: str, text: str) -> None:
        def _set() -> None:
            self.slots[kind] = text  # replace: the newest message wins
            self.event.set()
        try:
            self.loop.call_soon_threadsafe(_set)
        except RuntimeError:
            pass  # loop closed: the subscriber is going away


class LiveProcessor:
    """Per-frame analysis using the shared detector / tracker implementations."""

    def __init__(self, site: SiteModel, calibration: LiveCalibration, synthetic: bool, max_track_age_s: float = 2.0) -> None:
        from .crowd_tracking import build_tracker  # noqa: PLC0415
        from .detection import PersonDetectionEngine  # noqa: PLC0415
        from .tracking import MultiObjectTracker  # noqa: PLC0415

        self.site = site
        self.calibration = calibration
        self.projector = GroundProjector(site, calibration)
        if not self.projector.valid:
            raise SourceError("INVALID_CALIBRATION", f"Calibration is invalid: {self.projector.message}")
        self.synthetic = synthetic
        self.detector = PersonDetectionEngine(self.projector.engine)
        self.identity, self.identity_info = build_tracker("auto", frame_rate=10.0)
        self.kinematics = MultiObjectTracker(self.projector.engine, max_age_frames=25, min_hits=1, max_history_length=30)
        self.max_track_age_s = max_track_age_s
        self.masks = SiteMasks(site)
        self.visible = self.projector.visible_mask(self.masks.centers)
        self.planner = RoutePlanner(site, self.masks)
        self.guidance = GuidanceController(self.planner)
        self.last_seen: dict[int, float] = {}
        self.conf_window: deque[float] = deque(maxlen=60)
        self.failed_window: deque[bool] = deque(maxlen=30)

    @property
    def metric(self) -> bool:
        return self.calibration.confirmed

    def process(self, frame: Frame) -> dict[str, Any]:
        from .schemas import BoundingBox  # noqa: PLC0415

        img = frame.image
        h, w = img.shape[:2]
        if (w, h) != tuple(self.calibration.frame_size):
            raise SourceError("FRAME_SIZE_CHANGED", f"Frame size changed to {w}×{h}; recalibrate")
        failed = False
        if frame.synthetic_boxes is not None:
            raw = [Detection(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in frame.synthetic_boxes]
            backend = "synthetic ground truth"
        else:
            try:
                boxes = self.detector.detect(img, confidence_threshold=0.3)
                raw = [Detection(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in boxes]
            except Exception as exc:  # noqa: BLE001 - recorded as a detection failure, never as an empty scene
                log.warning("Detection failed: %s", exc)
                raw, failed = [], True
            backend = self.detector.backend
        self.failed_window.append(failed)
        self.conf_window.extend(d.confidence for d in raw)
        now = frame.captured_at
        objs = [] if failed else [o for o in self.identity.update(raw, now) if o.confirmed]

        dets, ids = [], []
        for o in objs:
            foot = ((o.box[0] + o.box[2]) / 2, o.box[3])
            g = self.projector.to_ground(foot)
            if g is None:
                continue
            canvas = (g[0] / self.projector.mx, g[1] / self.projector.my)
            bb = BoundingBox(x1=o.box[0], y1=o.box[1], x2=o.box[2], y2=o.box[3], confidence=round(min(1.0, max(0.0, o.confidence)), 4))
            dets.append((bb, foot, canvas))
            ids.append(o.track_id)
        kin = {t.track_id: t for t in self.kinematics.update(dets, frame_idx=frame.index, timestamp_s=now, external_ids=ids)} if not failed else {}
        for tid in ids:
            self.last_seen[tid] = now

        people: list[GroundPerson] = []
        tracks_out = []
        for tid, t in kin.items():
            seen_ago = now - self.last_seen.get(tid, now)
            if seen_ago > self.max_track_age_s:
                continue
            gx, gy = t.birdseye_point[0] * self.projector.mx, t.birdseye_point[1] * self.projector.my
            box = t.camera_bbox
            unc = self.projector.footprint_uncertainty(t.camera_ground_point, box.y2 - box.y1) + 0.3 * seen_ago
            weight = 1.0 if seen_ago < 1e-6 else max(0.0, 1.0 - seen_ago / self.max_track_age_s) * 0.7
            vel = t.velocity_vector_mps or (0.0, 0.0)
            people.append(GroundPerson(gx, gy, weight=weight, sigma=max(self.site.kde_sigma_m, unc), speed=t.speed_mps, track_id=tid))
            tracks_out.append({
                "id": tid, "box": [round(box.x1 / w, 4), round(box.y1 / h, 4), round(box.x2 / w, 4), round(box.y2 / h, 4)],
                "conf": round(t.confidence, 3), "foot_px": [round(t.camera_ground_point[0], 1), round(t.camera_ground_point[1], 1)],
                "ground": [round(gx, 2), round(gy, 2)], "vel": [round(vel[0], 2), round(vel[1], 2)],
                "speed": round(t.speed_mps, 2), "heading": t.heading_deg, "last_seen": round(self.last_seen.get(tid, now), 3),
                "seen_ago_s": round(seen_ago, 2), "predicted": seen_ago > 1e-6, "uncertainty_m": round(unc, 2),
                "in_view": 0 <= gx <= self.site.width_m and 0 <= gy <= self.site.height_m,
            })
        for tid in list(self.last_seen):
            if now - self.last_seen[tid] > 10 * self.max_track_age_s:
                del self.last_seen[tid]
        occ = compute_occupancy(self.site, self.masks, people, self.visible, feed_ok=not failed, metric=self.metric)
        return {"tracks": tracks_out, "occupancy": occ, "detections": len(raw), "detector": backend, "failed": failed,
                "frame_w": w, "frame_h": h}


class LiveMonitor:
    def __init__(self, store=None) -> None:
        self.store = store
        self.alerts = AlertManager()
        self._lock = threading.RLock()
        self._cond = threading.Condition()
        self._subs: list[Subscriber] = []
        self._threads: list[threading.Thread] = []
        self._running = False
        self.source: Optional[FrameSource] = None
        self.source_key: Optional[str] = None
        self.processor: Optional[LiveProcessor] = None
        self.status = "idle"
        self.error: Optional[dict[str, str]] = None
        self._latest: Optional[Frame] = None
        self._last_frame_at = 0.0
        self.stats = self._fresh_stats()
        self.seq = 0
        self.last_snapshot: Optional[str] = None
        self.origin: dict[str, Any] = {"mode": "auto"}
        self.max_fps = 12.0
        self.site = self._load("crowdguard.site", SiteModel) or default_site()
        self.calibrations: dict[str, LiveCalibration] = {
            k: LiveCalibration.model_validate(v) for k, v in (self._raw("crowdguard.calibrations") or {}).items()}
        self._zone_hist: dict[str, deque] = {}
        self._route: dict[str, Any] = {"available": False, "reason": "monitoring not started"}
        self._last_guidance = 0.0
        self._last_preview = 0.0

    # ---- persistence ------------------------------------------------------------
    def _raw(self, key: str):
        try:
            return self.store.get_setting(key) if self.store is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _load(self, key: str, model):
        raw = self._raw(key)
        try:
            return model.model_validate(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def _save(self) -> None:
        if self.store is None:
            return
        self.store.set_setting("crowdguard.site", self.site.model_dump(mode="json"))
        self.store.set_setting("crowdguard.calibrations", {k: v.model_dump(mode="json") for k, v in self.calibrations.items()})

    @staticmethod
    def _fresh_stats() -> dict[str, Any]:
        return {"fps": 0.0, "capture_fps": 0.0, "proc_ms": None, "e2e_ms": None, "processed": 0, "captured": 0,
                "skipped": 0, "detections": 0, "tracks": 0, "started_at": None, "reconnects": 0}

    # ---- subscribers --------------------------------------------------------------
    def subscribe(self, loop: asyncio.AbstractEventLoop, frames: bool) -> Subscriber:
        sub = Subscriber(loop=loop, frames=frames)
        with self._lock:
            self._subs.append(sub)
            if self.last_snapshot:
                sub.slots["snapshot"] = self.last_snapshot
                sub.event.set()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def _publish(self, kind: str, text: str) -> None:
        with self._lock:
            subs = list(self._subs)
        for s in subs:
            if kind == "frame" and not s.frames:
                continue
            s.offer(kind, text)

    # ---- control --------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {"status": self.status, "error": self.error, "source": self.source.describe() if self.source else None,
                    "source_key": self.source_key, "stats": dict(self.stats), "seq": self.seq, "origin": self.origin,
                    "calibration": self.current_calibration_info(), "subscribers": len(self._subs), "max_fps": self.max_fps}

    def current_calibration_info(self) -> Optional[dict[str, Any]]:
        if self.processor is None:
            return None
        c = self.processor.calibration
        label = ("simulated geometry (exact)" if self.processor.synthetic else
                 "measured by an operator" if c.confirmed else "assumed (not measured)")
        return {"image_points": c.image_points, "frame_size": c.frame_size, "confirmed": c.confirmed,
                "metric": self.processor.metric, "source": label,
                "visible_fraction": round(float(self.processor.visible.mean()), 3)}

    def start(self, source: FrameSource, key: str, max_fps: float | None = None) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self.status, self.error = "starting", None
        try:
            source.open()
        except SourceError as exc:
            with self._lock:
                self.status, self.error = "error", {"code": exc.code, "message": exc.message}
            self._broadcast_status()
            raise
        with self._lock:
            self.source, self.source_key = source, key
            if max_fps:
                self.max_fps = max_fps
            self.stats = self._fresh_stats()
            self.stats["started_at"] = time.time()
            self._latest = None
            self._zone_hist.clear()
            self.alerts.clear_all()
            self._build_processor()
            self._running = True
            self.status = "running"
            self._last_frame_at = time.time()
        for target, name in ((self._capture_loop, "cg-capture"), (self._process_loop, "cg-process")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self._broadcast_status()
        return self.describe()

    def _build_processor(self) -> None:
        src = self.source
        assert src is not None and self.source_key is not None
        cal = self.calibrations.get(self.source_key)
        if isinstance(src, SyntheticSource):
            # The simulated camera geometry is exact by construction.
            cal = LiveCalibration(image_points=src.default_image_points(), frame_size=(src.width, src.height), confirmed=True)
        elif cal is None:
            cal = LiveCalibration.default_for(src.width, src.height)
        else:
            cal = cal.rescaled(src.width, src.height)
        self.processor = LiveProcessor(self.site, cal, synthetic=isinstance(src, SyntheticSource))
        self._route = {"available": False, "reason": "waiting for the first frame"}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
        with self._cond:
            self._cond.notify_all()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []
        with self._lock:
            if self.source is not None:
                self.source.close()
            self.source = None
            self.processor = None
            if self.status not in ("error",):
                self.status = "idle"
        self._broadcast_status()
        return self.describe()

    def set_site(self, site: SiteModel) -> None:
        with self._lock:
            self.site = site
            if self.processor is not None:
                self._build_processor()
            self._save()

    def set_calibration(self, cal: LiveCalibration, width_m: float | None, height_m: float | None) -> dict[str, Any]:
        with self._lock:
            if self.source is None or self.source_key is None:
                raise SourceError("NOT_RUNNING", "Start a camera before calibrating it")
            if isinstance(self.source, SyntheticSource):
                raise SourceError("SYNTHETIC", "The simulated camera is already exactly calibrated")
            if width_m and height_m and (abs(width_m - self.site.width_m) > 1e-6 or abs(height_m - self.site.height_m) > 1e-6):
                self.site = self.site.scaled(width_m, height_m)
            probe = GroundProjector(self.site, cal)
            if not probe.valid:
                raise SourceError("INVALID_CALIBRATION", probe.message)
            self.calibrations[self.source_key] = cal
            self._build_processor()
            self._save()
            return self.current_calibration_info() or {}

    def set_origin(self, origin: dict[str, Any]) -> None:
        with self._lock:
            self.origin = origin
            if self.processor is not None:
                self.processor.guidance.reset()

    def set_portal(self, portal_id: str, available: bool) -> None:
        with self._lock:
            portals = [p.model_copy(update={"available": available}) if p.id == portal_id else p for p in self.site.portals]
            if not any(p.id == portal_id for p in self.site.portals):
                raise SourceError("UNKNOWN_PORTAL", f"No exit or entrance '{portal_id}'")
            self.site = self.site.model_copy(update={"portals": portals})
            if self.processor is not None:
                self.processor.site = self.site
                self.processor.planner.site = self.site
            self._save()

    # ---- threads ----------------------------------------------------------------------
    def _capture_loop(self) -> None:
        fails, backoff = 0, 1.0
        cap_count, cap_t0 = 0, time.time()
        while self._running:
            src = self.source
            if src is None:
                break
            try:
                frame = src.read()
            except Exception as exc:  # noqa: BLE001
                log.warning("Capture error: %s", exc)
                frame = None
            if frame is None:
                fails += 1
                if fails >= 5 or time.time() - self._last_frame_at > STALE_AFTER_S:
                    self._on_feed_lost(src)
                    if not src.reconnectable:
                        if src.kind == "recorded_video":
                            with self._lock:
                                self.status = "ended"
                            self._broadcast_status()
                        break
                    time.sleep(backoff)
                    backoff = min(5.0, backoff * 2)
                    try:
                        src.close()
                        src.open()
                        fails = 0
                        backoff = 1.0
                        with self._lock:
                            self.stats["reconnects"] += 1
                            self.status = "running"
                            self.error = None
                        self.alerts.event(f"reconnected:{self.source_key}", time.time(), severity="info", kind="camera_reconnected",
                                          location={"camera": src.label}, observation=f"{src.label} is delivering frames again",
                                          action="Check the map for gaps while the feed was down.")
                        self._broadcast_status()
                    except SourceError as exc:
                        with self._lock:
                            self.error = {"code": exc.code, "message": exc.message}
                else:
                    time.sleep(0.02)
                continue
            fails = 0
            cap_count += 1
            with self._cond:
                if self._latest is not None and self._latest.index != getattr(self, "_last_processed_index", -1):
                    self.stats["skipped"] += 1  # an unprocessed frame is replaced by a newer one
                self._latest = frame
                self._last_frame_at = frame.captured_at
                self.stats["captured"] += 1
                self._cond.notify()
            el = time.time() - cap_t0
            if el >= 2.0:
                self.stats["capture_fps"] = round(cap_count / el, 1)
                cap_count, cap_t0 = 0, time.time()

    def _on_feed_lost(self, src: FrameSource) -> None:
        with self._lock:
            if self.status == "disconnected":
                return
            self.status = "disconnected"
        now = time.time()
        self.alerts.event(f"disconnected:{self.source_key}", now, severity="critical", kind="camera_disconnected",
                          location={"camera": src.label}, observation=f"No frames from {src.label} for {STALE_AFTER_S:.0f} s",
                          action="Treat the area as unobserved: send a steward and check the camera connection.")
        self._broadcast_status()

    def _process_loop(self) -> None:
        last_index = -1
        fps_ema = None
        last_t = None
        while self._running:
            with self._cond:
                if self._latest is None or self._latest.index == last_index:
                    self._cond.wait(timeout=0.5)
                frame = self._latest
            if not self._running:
                break
            if frame is None or frame.index == last_index:
                if time.time() - self._last_frame_at > STALE_AFTER_S and self.processor is not None:
                    self._publish_snapshot(None, stale=True)  # keep clients informed: everything unknown
                continue
            last_index = frame.index
            self._last_processed_index = frame.index
            proc = self.processor
            if proc is None:
                continue
            t0 = time.perf_counter()
            try:
                result = proc.process(frame)
            except SourceError as exc:
                with self._lock:
                    self.error = {"code": exc.code, "message": exc.message}
                    self.status = "error"
                self._broadcast_status()
                time.sleep(0.5)
                continue
            except Exception as exc:  # noqa: BLE001
                log.exception("Processing failed")
                with self._lock:
                    self.error = {"code": "PROCESSING_FAILED", "message": f"{type(exc).__name__}: {exc}"}
                time.sleep(0.2)
                continue
            proc_ms = (time.perf_counter() - t0) * 1000
            now = time.time()
            if last_t is not None:
                inst = 1.0 / max(1e-3, now - last_t)
                fps_ema = inst if fps_ema is None else 0.8 * fps_ema + 0.2 * inst
            last_t = now
            with self._lock:
                if self.status in ("disconnected", "starting"):
                    self.status = "running"
                self.stats.update(fps=round(fps_ema or 0.0, 1), proc_ms=round(proc_ms, 1), e2e_ms=round((now - frame.captured_at) * 1000, 1),
                                  processed=self.stats["processed"] + 1, detections=result["detections"], tracks=len(result["tracks"]))
            self._publish_snapshot((frame, result))
            if now - self._last_preview >= FRAME_PREVIEW_INTERVAL_S and any(s.frames for s in self._subs):
                self._last_preview = now
                self._publish_frame(frame)
            # Optional cap on processing rate (keeps the laptop responsive).
            spare = 1.0 / self.max_fps - (time.time() - now + proc_ms / 1000)
            if spare > 0:
                time.sleep(spare)

    # ---- snapshot -------------------------------------------------------------------------
    def _origin_point(self, occ: dict[str, Any]) -> tuple[tuple[float, float], str]:
        o = self.origin
        if o.get("mode") == "point":
            return (float(o["x"]), float(o["y"])), "selected point"
        if o.get("mode") == "zone":
            z = next((z for z in self.site.zones if z.id == o.get("zone_id")), None)
            if z:
                return zone_centroid(z), z.name
        # auto: the busiest observed zone, else the first entrance
        known = [z for z in occ["zones"] if z["occupancy_pct"] is not None and z["population"]]
        if known:
            zb = max(known, key=lambda z: z["occupancy_pct"])
            z = next(x for x in self.site.zones if x.id == zb["id"])
            return zone_centroid(z), f"{z.name} (busiest zone)"
        ent = next((p for p in self.site.portals if p.kind == "entrance"), None)
        if ent:
            return ent.center, ent.name
        return (self.site.width_m / 2, self.site.height_m / 2), "site centre"

    def _alerts_from(self, occ: dict[str, Any], result: dict[str, Any], now: float, route_change: Optional[str]) -> list[dict[str, Any]]:
        new = []

        def add(a):
            if a:
                new.append(a)
        proc = self.processor
        for z in occ["zones"]:
            loc = {"zone": z["name"], "zone_id": z["id"]}
            pct = z["occupancy_pct"]
            hist = self._zone_hist.setdefault(z["id"], deque(maxlen=120))
            if z["population"] is not None:
                hist.append((now, z["population"]))
            add(self.alerts.observe(f"capacity:{z['id']}", pct is not None and pct >= 100, now, severity="critical", kind="zone_capacity_exceeded",
                                    location=loc, observation=f"{z['population']} people for a capacity of {z['capacity']} ({pct}%)",
                                    action="Stop admitting people into this zone and open an alternative area.", metrics={"occupancy_pct": pct}))
            add(self.alerts.observe(f"near:{z['id']}", pct is not None and 85 <= pct < 100, now, severity="high", kind="zone_near_capacity",
                                    location=loc, observation=f"{z['name']} at {pct}% of capacity",
                                    action="Prepare to redirect arrivals; brief stewards.", metrics={"occupancy_pct": pct}))
            past = [p for t, p in hist if now - t >= 15]
            if past and z["population"] is not None:
                rise = z["population"] - past[-1]
                add(self.alerts.observe(f"rapid:{z['id']}", rise >= max(3, 0.25 * z["capacity"]), now, severity="high", kind="rapid_accumulation",
                                        location=loc, observation=f"+{rise:.0f} people in about 15 s (now {z['population']})",
                                        action="Watch inflow; slow arrivals if it continues.", metrics={"rise": rise}))
            slow = z["mean_speed"] is not None and z["population"] is not None and z["population"] >= 3 and z["mean_speed"] < 0.3
            add(self.alerts.observe(f"slow:{z['id']}", slow, now, severity="medium", kind="flow_slowed", location=loc,
                                    observation=f"Mean walking speed {z['mean_speed']} m/s with {z['population']} people"
                                    + ("" if proc and proc.metric else " (assumed scale)"),
                                    action="Check for a stoppage or queue spilling into the walkway."))
        state = occ["_state"]
        cong_m2 = occ["summary"]["congested_m2"]
        add(self.alerts.observe("congestion", cong_m2 >= 2 * self.site.cell_m ** 2, now, severity="high" if cong_m2 >= 8 else "medium",
                                kind="corridor_congestion", location={"area_m2": cong_m2},
                                observation=f"{cong_m2} m² of walkable floor above the congestion threshold",
                                action="Hold flows towards the congested area and use the recommended route.", metrics={"congested_m2": cong_m2}))
        for p in self.site.portals:
            if p.kind == "entrance":
                continue
            usable, why = proc.planner.exit_status(p, state) if proc else (True, "")
            add(self.alerts.observe(f"exit:{p.id}", not usable, now, severity="critical" if p.kind == "emergency_exit" else "high",
                                    kind="exit_unavailable", location={"exit": p.name, "exit_id": p.id},
                                    observation=f"{p.name} {why}",
                                    action="Clear the obstruction; never close an emergency exit. Guidance avoids it meanwhile."))
        confs = list(proc.conf_window) if proc else []
        fail_rate = (sum(proc.failed_window) / len(proc.failed_window)) if proc and proc.failed_window else 0
        degraded = (len(confs) >= 10 and float(np.mean(confs)) < 0.4) or fail_rate > 0.2
        add(self.alerts.observe("detector", degraded, now, severity="medium", kind="detection_degraded",
                                location={"camera": self.source.label if self.source else ""},
                                observation=(f"Detection failures on {fail_rate:.0%} of recent frames" if fail_rate > 0.2
                                             else f"Mean detection confidence {np.mean(confs):.2f}" if confs else ""),
                                action="Check lighting, focus and camera angle; counts may be low."))
        if route_change:
            add(self.alerts.event(f"route:{hash(route_change) % 1000}", now, severity="medium", kind="route_changed",
                                  location={"origin": self._route.get("origin")}, observation=route_change,
                                  action="Confirm the new route with stewards before redirecting people."))
        return new

    def _publish_snapshot(self, item: Optional[tuple[Frame, dict[str, Any]]], stale: bool = False) -> None:
        proc = self.processor
        if proc is None:
            return
        now = time.time()
        if stale or item is None:
            occ = compute_occupancy(self.site, proc.masks, [], proc.visible, feed_ok=False, metric=proc.metric)
            result = {"tracks": [], "detections": 0, "detector": proc.detector.backend, "failed": False,
                      "frame_w": proc.calibration.frame_size[0], "frame_h": proc.calibration.frame_size[1]}
            frame = None
        else:
            frame, result = item
            occ = result["occupancy"]
        route_change = None
        if now - self._last_guidance >= GUIDANCE_INTERVAL_S:
            self._last_guidance = now
            origin, label = self._origin_point(occ)
            index = (occ["_density"] / self.site.congested_density)
            self._route, route_change = proc.guidance.update(origin, label, occ["_state"], index, now)
        new_alerts = self._alerts_from(occ, result, now, route_change)
        with self._lock:
            self.seq += 1
            src = self.source.describe() if self.source else None
            snap = {
                "type": "snapshot", "seq": self.seq, "server_time": round(now, 3),
                "frame": {"index": frame.index if frame else None, "captured_at": round(frame.captured_at, 3) if frame else None,
                          "width": result["frame_w"], "height": result["frame_h"]},
                "source": src, "status": "stale" if stale else self.status, "error": self.error,
                "stats": dict(self.stats), "detector": result["detector"], "detection_failed": result["failed"],
                "tracker": proc.identity_info.get("tracker"),
                "calibration": self.current_calibration_info(),
                "site": {"id": self.site.id, "width_m": self.site.width_m, "height_m": self.site.height_m},
                "tracks": result["tracks"],
                "grid": {k: v for k, v in occ.items() if not k.startswith("_") and k not in ("zones", "summary")},
                "space": occ["summary"], "zones": occ["zones"],
                "zone_history": {zid: [round(p, 1) for _, p in list(h)[-60::4]] for zid, h in self._zone_hist.items()},
                "route": self._route, "alerts": self.alerts.snapshot(), "new_alerts": new_alerts,
            }
            text = json.dumps(snap, separators=(",", ":"), default=str)
            self.last_snapshot = text
        self._publish("snapshot", text)

    def _publish_frame(self, frame: Frame) -> None:
        import cv2  # noqa: PLC0415

        img = frame.image
        h, w = img.shape[:2]
        tw = min(640, w)
        small = cv2.resize(img, (tw, int(h * tw / w)), interpolation=cv2.INTER_AREA) if tw < w else img
        ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 62])
        if not ok:
            return
        msg = {"type": "frame", "index": frame.index, "captured_at": round(frame.captured_at, 3), "width": w, "height": h,
               "image": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")}
        self._publish("frame", json.dumps(msg, separators=(",", ":")))

    def _broadcast_status(self) -> None:
        self._publish("status", json.dumps({"type": "status", **self.describe()}, default=str))

    def hello(self) -> str:
        return json.dumps({"type": "status", **self.describe()}, default=str)


def site_geometry(site: SiteModel) -> dict[str, Any]:
    """Site config plus derived per-cell masks for the map (blocked cells, zone membership)."""
    masks = SiteMasks(site)
    return {**site.model_dump(mode="json"), "rows": site.rows, "cols": site.cols,
            "blocked": "".join("1" if b else "0" for b in masks.blocked.reshape(-1)),
            "portal_capacity_ppm": {p.id: p.capacity_ppm for p in site.portals},
            "zone_area_m2": {z.id: round(z.area_m2, 1) for z in site.zones}}


__all__ = ["LiveMonitor", "LiveProcessor", "Subscriber", "site_geometry"]
