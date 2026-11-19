# CROWDGUARD — Architecture

CROWDGUARD is a crowd-safety monitoring prototype for public events, built on the OMNIFORGE framework.
It estimates how many people are in each zone, flags overcrowding and dangerous build-up early, forecasts
capacity breaches, and proposes safer movement routes, with every number labelled as **observed**, **estimate**
or **synthetic**.

> CROWDGUARD does not certify that an event is safe. Its counts are estimates, not ground truth. Human
> organisers make every intervention decision, and no software recommendation can close or restrict an emergency exit.

## 1. Run it

```bash
cd backend && python -m uvicorn app.main:app --port 8000      # API + built UI at http://127.0.0.1:8000
cd frontend && npm run build                                   # (re)build the UI that FastAPI serves
# or for UI development: cd frontend && npm run dev            # http://localhost:5173 (proxies /api)
```

Optional environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `CROWDGUARD_YOLO_WEIGHTS` | auto-search | Path to a local YOLO `.pt` file. **Nothing is ever downloaded.** Search order: this variable, `backend/models/{yolo11n,yolov8n,…}.pt`, then the user's home folder. |
| `CROWDGUARD_DETECTOR` | `auto` | `auto` (YOLO, else OpenCV HOG), `yolo`, or `hog` |
| `CROWDGUARD_MAX_VIDEO_MB` | `100` | Upload cap for video |
| `GEMINI_API_KEY` | unset | Enables Gemini briefings via the existing AI provider abstraction; otherwise the labelled local fallback is used |

## 2. Shape of the system

```mermaid
flowchart LR
  subgraph UI["React command centre (8 screens)"]
    CC[Command Centre] --- LM[Live Monitoring] --- ZI[Zone Intelligence] --- CF[Forecasting]
    MP[Movement Planner] --- IM[Incidents] --- AN[Analytics] --- AV[Audit & Verification]
  end
  UI -- "/api/crowdguard/*" --> R[Thin FastAPI routes]
  R --> REG{{"Engine registry<br/>policy gate · validation · audit"}}
  REG --> CROWD[crowd engine]
  CROWD -- "decision.evaluate_rules" --> DEC[decision]
  CROWD -- "ml.forecast" --> ML[ml]
  CROWD -- "ai.explain" --> AI[ai → Gemini or local fallback]
  CROWD -- "crypto.hash / merkle_root" --> CR[crypto]
  CROWD --> SVC
  subgraph SVC["app/crowdguard (plain, independently testable services)"]
    DET[crowd_detection] --> TRK[crowd_tracking] --> ZM[zone_manager]
    ZM --> DEN[density_estimator] --> CON[congestion_detector]
    FLOW[crowd_flow] --> CON
    FC[crowd_forecaster] --> CON
    CON --> REC[safety_recommendations] --> RO[route_optimizer · NetworkX]
    SIM[simulation] --> AN2[analysis]
    MED[media_analysis] --> DET
  end
  REG --> DB[(SQLite: executions · hash-chained audit · documents · crowd_incidents)]
```

The six OMNIFORGE engines (security, ai, ml, crypto, data, decision) and the nine original domain adapters are
unchanged. CROWDGUARD adds:

* **`crowd` engine** (`backend/app/engines/crowd/engine.py`): the seventh engine. It exposes the services as typed,
  policy-checked operations and *reuses* the other engines through the registry instead of re-implementing them.
* **`crowd_safety` domain adapter** (`backend/app/domains/adapters/crowd_safety.py`): the tenth adapter. A declarative
  pipeline (snapshot → backtested forecast → per-zone risk score → relief route → briefing → evidence hash) that runs in the
  generic OMNIFORGE workspace and is covered by the parametrised pipeline test.
* **`/api/crowdguard/*` routes** (`backend/app/api/crowdguard.py`): thin wrappers that call the engine through the registry,
  plus background jobs for media analysis.
* **Eight React screens** (`frontend/src/crowdguard/`), integrated into the enhanced OMNIFORGE shell from `feature/omniforge-frontend`.

## 3. Services (`backend/app/crowdguard/`)

| Module | Responsibility |
|---|---|
| `zone_manager.py` | Polygon zones, shoelace area, ray-casting point-in-polygon (edges count as inside), per-zone counts; overlapping zones resolve to the smallest polygon. People are assigned by their **foot point** (bottom-centre of the box). |
| `crowd_detection.py` | `YoloPersonDetector` (Ultralytics, person class only, local weights only, `YOLO_OFFLINE=true` so no downloads or telemetry) and `HogPersonDetector` (OpenCV, no weights). The status records what was searched, what loaded and whether a test inference passed. |
| `crowd_tracking.py` | `ByteTrackTracker` (Ultralytics BYTETracker fed with our detections) or a deterministic ByteTrack-style `IoUTracker` fallback. `TrackHistory` gives unique ids per zone, zone-to-zone transitions and fragmentation. Repeated detections of one person are never counted twice. |
| `density_estimator.py` | Occlusion-corrected estimate with an interval (`estimate = observed / recall(density)`), occupancy %, density, Fruin level of service, bands (normal / elevated / high / critical / **unknown**), a heuristic confidence and a data-quality label. Stale, missing and detector-error feeds carry the last value forward with a widening interval or report **unknown**, never zero. |
| `crowd_flow.py` | Track velocities (least squares over a window; px/s, or m/s with calibration), direction histogram, coherence, stationary and counter-flow share, the Weidmann speed–density relation, and net zone flow vectors from corridor flows. |
| `congestion_detector.py` | Twelve alert rules generated from venue thresholds in the decision engine's JSON DSL: overcrowded, near capacity, dangerous density, rapid build-up, forecast breach, slow queue (Little's law), slow crowd, stale feed, detection failure, low confidence, exit blocked and bottleneck. Evaluation is delegated to `decision.evaluate_rules`. |
| `crowd_forecaster.py` | Deterministic forecast: persistence for fewer than 3 points, a linear trend for fewer than 8, otherwise damped Holt. The band comes from out-of-sample residuals and widens with the horizon. Also time to capacity, a possible breach from the upper band, and a heuristic probability of exceeding capacity. `rolling_backtest` scores it against persistence. |
| `venue.py` | Venue config → NetworkX graph (zones, junctions, gates, exits). Corridor capacity = width × 82 people/m/min. |
| `route_optimizer.py` | Safety-weighted Dijkstra plus Yen k-shortest paths. Hard rules: never enter a high/critical zone (except the source), never pass through a service queue, avoid blocked corridors and exits, and destinations must have fresh data and spare capacity on the **upper** estimate (≤ 85 % after arrival). It splits the group across destinations and separately assesses the distance-shortest path, giving reasons when it is rejected. |
| `safety_recommendations.py` | Ranked, explained actions (relieve zone, meter entry, clear exit, re-route egress, verify feed, manage queue, steward bottleneck). Each one has `requires_human_decision = True`. `validate_action` refuses any restrictive action that targets an emergency exit. |
| `analysis.py` | One snapshot: readings → forecasts → facts → alerts → route state → recommendations → summary. Shared by simulation and live assessment. |
| `simulation.py` | The deterministic synthetic festival (see §5) and a counterfactual run without intervention. |
| `media_analysis.py` | Video/image ingestion: magic-byte sniffing, frame sampling (~5 fps, capped at 30 s / 180 frames), detection → tracking → zones → flow → estimates. Returns keyframes with overlays and maps camera zones to venue zones, with coverage-based extrapolation labelled as such. |

## 4. API (`/api/crowdguard`)

| Method & path | Engine op | Notes |
|---|---|---|
| `GET /venue` | `crowd.venue` | Zones, graph, thresholds, camera layouts |
| `GET /status` | `crowd.status` | Verified detector/weights, tracker, routing library, AI provider |
| `POST /simulation` | `crowd.simulate` | `{seed, intervention, exit_blockage, feed_outage, tick?}`. Full timeline, or one tick plus its history. Cached. |
| `POST /assess` | `crowd.assess` | Live observations → readings, alerts, recommendations. Zones without an observation are reported as **missing**, not empty. |
| `POST /route` | `crowd.route` | `{source, purpose: relieve|egress, group_size, tick or zones, blocked_edges, blocked_nodes}` |
| `POST /forecast` | `crowd.forecast` | Deterministic forecast, plus `ml.forecast` when there are at least 16 points, plus a rolling backtest |
| `POST /explain` | `crowd.explain` | `ai.explain` briefing (Gemini if configured, otherwise local fallback; the provider is reported) |
| `POST /media`, `POST /media/sample`, `GET /media/jobs/{id}` | `crowd.analyse_media` | Background job with progress. Uploads are stored by SHA-256 and audited. |
| `GET/POST /incidents`, `POST /incidents/{id}/actions`, `GET /incidents/{id}/verify` | `crowd.incident_*` | Human-only lifecycle with a four-eyes close, hash-chained events and a Merkle seal |

Each response is the standard OMNIFORGE envelope (`success, result, warnings, metadata, error`), and each call is recorded in
`executions` and, for writes, in the hash-chained audit log. Simulation responses are gzip-compressed (~130 KB for 66 minutes).

## 5. The demonstration scenario (synthetic, deterministic)

Riverside Open-Air Festival (fictional): 8 zones, 2 junctions, 2 gates and 2 emergency exits, from 18:00 to 19:05, seed 2026.
It uses a macroscopic reservoir model with corridor throughput caps that depend on density. A synthetic camera per zone undercounts
with density, and the normal estimator turns its readings into estimates. Each scenario event comes from the alerts the system actually raised:

| Clock | What happens |
|---|---|
| 18:20 | First warning: Main Stage filling at ≥ 2 % of capacity per minute (52 %). Simulated incident INC-SIM-001 opened. |
| 18:26 | Bar-queue camera returns detector errors for 2 min. Shown as "detection failed", not as an empty zone. |
| 18:32 | Forecast predicts a capacity breach; near-capacity alert. The route planner proposes a relief route. |
| 18:37 | Main Stage over safe capacity (critical). |
| 18:40 | Organisers approve the recommendation (simulated): entry metered, arrivals redirected, relief to Second Stage and Food Court. |
| 18:41 | Peak at ~104.6 % (estimate). Without the intervention the same scenario peaks at ~158 % (counterfactual). |
| 18:44 | East Emergency Exit E1 obstructed. Exit-blocked alert; egress is re-planned to W1 / North Gate. |
| 18:49–18:53 | Food Court camera drops out. Stale-feed alert; the planner stops using Food Court as a destination. |
| 18:57 → 19:04 | Main Stage back below 85 %, then resolved after 5 stable minutes. E1 cleared at 18:58. |

Forecast check (rolling origin, 10-min horizon, Main Stage): MAE ≈ 1,125 people vs persistence ≈ 1,506. These figures come
from the synthetic scenario only and say nothing about accuracy on real cameras.

## 6. Safety and reliability decisions

* **Unknown ≠ zero.** Feed states are `ok | stale | missing | detector_error`. Unusable feeds carry the last value forward
  with drift-widened bounds and decaying confidence, or report `unknown`. Alerts fire for them, attendance totals say they exclude
  unknown zones, and routing never chooses an unverified destination.
* **Estimates carry uncertainty.** The occlusion model (recall 0.95 → 0.55 as density rises, ±0.08) and Poisson-like counting
  noise give an interval. Confidence values are heuristic and labelled as such. All thresholds are illustrative and must be calibrated per venue.
* **Shortest ≠ safe.** The distance-shortest path is always assessed against the hard rules and reported with pass/fail per check.
* **Human in the loop.** Recommendations are advisory. Incident transitions need a human actor (AI actors are capped at read by the policy gate),
  and closing needs a second person.
* **Emergency exits.** `validate_action` refuses restrictive actions on emergency exits. The planner treats a blocked exit as an
  observed condition to route around and to clear; it never proposes closing one.
* **Integrity, without blockchain.** Incident evidence is SHA-256-hashed via the crypto engine, events are hash-chained, and closure is sealed
  with an RFC 6962-style Merkle root. `verify` recomputes all three, and a test edits the DB row and confirms tampering is detected.
* **Privacy.** No face recognition or re-identification is used. Track ids are ephemeral, and uploads are stored by hash on the local machine.

## 7. Verified vs fallback in this build

| Capability | Status on the build machine |
|---|---|
| YOLO person detection | **Verified**: local `yolov8n.pt` found in the user's home folder and a test inference passed. Weights are not in the repo (`*.pt` is git-ignored). |
| Tracking | **Verified**: Ultralytics BYTETracker (IoU tracker kept as fallback) |
| Routing | NetworkX 3.6.1 |
| LLM | **Not configured**: briefings use the deterministic local fallback and are labelled. The Gemini path was not exercised live. |
| Video test asset | A camera pan synthesised from Ultralytics' `bus.jpg`: detections are real, motion is artificial (labelled). No real crowd footage was available. |

## 8. Known limitations

* The macroscopic simulator is a demonstration model, not a validated pedestrian simulation.
* Camera zone polygons and metres-per-pixel must be configured per camera. Without calibration, speeds are px/s.
* The occlusion model is a generic assumption. Calibrate it against manual counts before trusting absolute numbers.
* Media jobs and the simulation cache are in-memory (lost on restart). Processing is CPU-only and capped at 30 s of video per job.
* Identity is still the simulated OMNIFORGE header identity. Put real authentication in front before any deployment.
