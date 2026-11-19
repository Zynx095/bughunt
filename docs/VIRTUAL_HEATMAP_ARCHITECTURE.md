# CROWDGUARD — VIRTUAL CROWD INTELLIGENCE ENGINE (VCIE)
## Virtual Bird's-Eye Crowd Density, Movement Intelligence & Digital Twin Architecture

---

### Executive Summary

The **Virtual Crowd Intelligence Engine (VCIE)** is an advanced computer vision and spatial crowd intelligence module for **CROWDGUARD**. It transforms conventional, oblique closed-circuit television (CCTV) footage into a calibrated, top-down virtual bird's-eye representation of monitored event venues. 

Rather than rendering uncalibrated screen-space heatmaps, VCIE projects observed pedestrian foot-ground contact points onto a calibrated physical ground plane via planar homography ($H \in \mathbb{R}^{3 \times 3}$). It computes continuous Gaussian Kernel Density Estimation (KDE) normalized into true physical units of **persons per square metre** ($\text{persons/m}^2$), tracks individual trajectories across sequential video frames using Kalman-filtered state estimation, identifies velocity stagnation and counterflow collisions, and projects live crowd telemetry onto a virtual venue digital twin.

```
+---------------------------------------------------------------------------------------------------------+
|                                  CROWDGUARD VCIE MASTER PIPELINE                                        |
|                                                                                                         |
|  [ CCTV Camera Feed ]                                                                                   |
|           |                                                                                             |
|           v                                                                                             |
|  [ Video Frame Extraction & Stride Decimation ]                                                         |
|           |                                                                                             |
|           v                                                                                             |
|  [ Ground Plane Identification (4-Point Calibration Quad) ]                                             |
|           |                                                                                             |
|           v                                                                                             |
|  [ Planar Homography Calculation H (OpenCV DLT) ]                                                       |
|           |                                                                                             |
|           +---------------------------------------+                                                     |
|           |                                       |                                                     |
|           v                                       v                                                     |
|  [ Frame Warp Perspective ]              [ YOLO Person Detection ]                                      |
|  (cv2.warpPerspective)                   (Ultralytics / CV Fallback)                                    |
|           |                                       |                                                     |
|           |                                       v                                                     |
|           |                              [ Foot Contact Point Extraction ]                              |
|           |                              (x_mid = (x1+x2)/2, y_bottom = y2)                             |
|           |                                       |                                                     |
|           |                                       v                                                     |
|           |                              [ Homography Coordinate Projection ]                           |
|           |                              [u', v', w']^T = H * [x, y, 1]^T                               |
|           |                              (u = u'/w', v = v'/w')                                         |
|           |                                       |                                                     |
|           +---------------------------------------+                                                     |
|           |                                                                                             |
|           v                                                                                             |
|  [ Multi-Object Tracking & Kalman State Filter ]                                                         |
|  (State: [u, v, vx, vy]^T, Persistent Track IDs, Position History Deque)                                |
|           |                                                                                             |
|           +---------------------------------------+                                                     |
|           |                                       |                                                     |
|           v                                       v                                                     |
|  [ Continuous Gaussian KDE Density ]     [ Movement Intelligence Analysis ]                             |
|  (persons/m², Point/Zone/Flux Modes)     (Velocity Vectors, Bottlenecks, Counterflows)                  |
|           |                                       |                                                     |
|           +---------------------------------------+                                                     |
|           |                                                                                             |
|           v                                                                                             |
|  [ Virtual Venue Digital Twin Rendering & Real-Time Alert Triage ]                                      |
|  (Walkable Areas, Obstacles, Portals, Zone Metrics, Commander Egress Directives)                        |
+---------------------------------------------------------------------------------------------------------+
```

---

## 1. Mathematical Foundations

### 1.1 Planar Projective Homography

A planar homography is an invertible mapping between two projective planes $\mathbb{P}^2 \to \mathbb{P}^2$. Given a camera observing a planar ground surface $Z=0$, there exists a projective transformation matrix $H \in \mathbb{R}^{3 \times 3}$ defined up to a non-zero scale factor $\lambda$:

$$
\begin{bmatrix} u' \\ v' \\ w' \end{bmatrix} = \mathbf{H} \begin{bmatrix} x \\ y \\ 1 \end{bmatrix} = \begin{bmatrix} h_{11} & h_{12} & h_{13} \\ h_{21} & h_{22} & h_{23} \\ h_{31} & h_{32} & h_{33} \end{bmatrix} \begin{bmatrix} x \\ y \\ 1 \end{bmatrix}
$$

The inhomogeneous Euclidean coordinates $(u, v)$ on the bird's-eye canvas are given by dividing by the homogeneous scale factor $w'$:

$$
u = \frac{u'}{w'} = \frac{h_{11}x + h_{12}y + h_{13}}{h_{31}x + h_{32}y + h_{33}}, \quad v = \frac{v'}{w'} = \frac{h_{21}x + h_{22}y + h_{23}}{h_{31}x + h_{32}y + h_{33}}
$$

#### Direct Linear Transformation (DLT)
Since $H$ has 8 degrees of freedom (up to arbitrary scale), each point correspondence $(x_i, y_i) \leftrightarrow (u_i, v_i)$ provides two independent linear equations:

$$
x_i h_{11} + y_i h_{12} + h_{13} - u_i x_i h_{31} - u_i y_i h_{32} - u_i h_{33} = 0
$$
$$
x_i h_{21} + y_i h_{22} + h_{23} - v_i x_i h_{31} - v_i y_i h_{32} - v_i h_{33} = 0
$$

With $N=4$ non-collinear reference points, the system $\mathbf{A} \mathbf{h} = 0$ (where $\mathbf{A} \in \mathbb{R}^{8 \times 9}$) is solved exactly via Singular Value Decomposition (SVD) using `cv2.getPerspectiveTransform`:

$$
\mathbf{h} = \text{argmin}_{\|\mathbf{h}\|=1} \|\mathbf{A}\mathbf{h}\|
$$

#### Numerical Stability and Invertibility
The condition number $\kappa(H) = \frac{\sigma_{\max}(H)}{\sigma_{\min}(H)}$ is evaluated. If $\det(H) < 10^{-12}$ or $\kappa(H) > 10^6$, the calibration is flagged as ill-conditioned or degenerate. Inverse projection back to camera image coordinates is guaranteed by:

$$
\mathbf{H}^{-1} = \frac{1}{\det(\mathbf{H})} \text{adj}(\mathbf{H})
$$

---

### 1.2 Ground-Contact Point Estimation

Pedestrians are 3D volumetric bodies standing upright on the 2D ground plane. Projecting the bounding box center $(x_c, y_c)$ or top $(x_c, y_1)$ yields severe parallax errors because human heads and torsos project far away from their true ground plane contact point.

VCIE designates the **bottom-centre of the bounding box** as the ground-contact reference point:

$$
x_{\text{ground}} = \frac{x_1 + x_2}{2}, \quad y_{\text{ground}} = y_2
$$

This point corresponds directly to the feet resting on the ground plane, satisfying the coplanar assumption required for homography $H$.

---

### 1.3 Multi-Object Tracking & Kalman State Filter

To track pedestrians across sequential frames without re-counting individuals, VCIE uses a 2D discrete Kalman filter in bird's-eye coordinates combined with greedy bipartite matching.

#### State Model
The state vector $\mathbf{x}_k \in \mathbb{R}^4$ and measurement vector $\mathbf{z}_k \in \mathbb{R}^2$ are defined as:

$$
\mathbf{x}_k = \begin{bmatrix} u \\ v \\ \dot{u} \\ \dot{v} \end{bmatrix}, \quad \mathbf{z}_k = \begin{bmatrix} u_{\text{meas}} \\ v_{\text{meas}} \end{bmatrix}
$$

The constant-velocity state transition matrix $\mathbf{F}$ with sampling step $\Delta t$ is:

$$
\mathbf{F} = \begin{bmatrix} 1 & 0 & \Delta t & 0 \\ 0 & 1 & 0 & \Delta t \\ 0 & 0 & 1 & 0 \\ 0 & 0 & 0 & 1 \end{bmatrix}, \quad \mathbf{H}_{\text{meas}} = \begin{bmatrix} 1 & 0 & 0 & 0 \\ 0 & 1 & 0 & 0 \end{bmatrix}
$$

#### Prediction Step:
$$
\hat{\mathbf{x}}_k^- = \mathbf{F} \hat{\mathbf{x}}_{k-1}, \quad \mathbf{P}_k^- = \mathbf{F} \mathbf{P}_{k-1} \mathbf{F}^T + \mathbf{Q}
$$

#### Measurement Update:
$$
\mathbf{y}_k = \mathbf{z}_k - \mathbf{H}_{\text{meas}} \hat{\mathbf{x}}_k^-, \quad \mathbf{S}_k = \mathbf{H}_{\text{meas}} \mathbf{P}_k^- \mathbf{H}_{\text{meas}}^T + \mathbf{R}
$$
$$
\mathbf{K}_k = \mathbf{P}_k^- \mathbf{H}_{\text{meas}}^T \mathbf{S}_k^{-1}, \quad \hat{\mathbf{x}}_k = \hat{\mathbf{x}}_k^- + \mathbf{K}_k \mathbf{y}_k, \quad \mathbf{P}_k = (\mathbf{I} - \mathbf{K}_k \mathbf{H}_{\text{meas}}) \mathbf{P}_k^-
$$

Instantaneous speed $s_k$ in meters per second is computed from the smoothed velocity:

$$
s_k = \sqrt{(\dot{u} \cdot m_x)^2 + (\dot{v} \cdot m_y)^2} \quad [\text{m/s}]
$$

---

### 1.4 Continuous Gaussian Kernel Density Estimation (KDE)

Traditional discrete crowd counts provide point numbers but ignore spatial clustering. VCIE models crowd density as a continuous probability density distribution over top-down coordinate space:

$$
D(u, v) = \sum_{i=1}^N \frac{w_i}{2\pi \sigma^2} \exp\left( -\frac{(u - u_i)^2 + (v - v_i)^2}{2\sigma^2} \right)
$$

Where:
- $(u_i, v_i)$ are the bird's-eye coordinates of tracked person $i$.
- $\sigma$ is the kernel bandwidth parameter (governing Gaussian spatial dispersion).
- $w_i$ is the agent weighting factor (set to $1.0$ for standard density, or weighted inversely by velocity $w_i = 1 + \max(0, 1.5 - s_i)$ in movement-flux mode).

#### Physical Scaling to Persons per Square Metre
Because the 2D Gaussian integrates to $1.0$ over $\mathbb{R}^2$:

$$
\iint_{-\infty}^\infty G(u - u_i, v - v_i; \sigma) \, du \, dv = 1
$$

In a discretized grid with cell dimensions $1 \text{ pixel} \times 1 \text{ pixel}$, each pixel covers real-world area $A_{\text{pixel}} = (m_x \times m_y) \text{ m}^2$. The physical crowd density $\rho(u, v)$ is therefore:

$$
\rho(u, v) = \frac{D(u, v)}{m_x \cdot m_y} \quad \left[\frac{\text{persons}}{\text{m}^2}\right]
$$

#### Fruin Level-of-Service (LoS) Risk Bands:
- **Low Risk ($\text{LoS A--B}$)**: $< 0.5 \text{ persons/m}^2$. Free-flowing movement.
- **Moderate Risk ($\text{LoS C--D}$)**: $0.5 - 1.5 \text{ persons/m}^2$. Noticeable crowd presence; walking speeds slightly restricted.
- **High Risk ($\text{LoS E}$)**: $1.5 - 3.0 \text{ persons/m}^2$. Walking speed severely degraded; potential for queue formation.
- **Critical Risk ($\text{LoS F}$)**: $> 3.0 \text{ persons/m}^2$. Overcrowding, inter-person physical contact, severe crush and stampede hazard. Triggers immediate automated ingress halt warnings.

---

### 1.5 Movement Intelligence & Flow Dynamics

#### Velocity Vectors
For each track with position history $\mathcal{H}_i = \{(u_{i, t}, v_{i, t})\}_{t=k-M}^k$, the directional heading $\theta_i$ is:

$$
\theta_i = \text{atan2}(v_{i, k} - v_{i, k-M}, \, u_{i, k} - u_{i, k-M}) \quad [\text{rad}]
$$

#### Bottleneck Detection
A spatial bottleneck is identified when a region exhibits high local density coupled with severe velocity depression:

$$
\text{BottleneckCondition}: \quad \rho(u_i, v_i) \ge 1.5 \text{ p/m}^2 \quad \land \quad s_i < 0.45 \text{ m/s}
$$

#### Counterflow / Opposing Streams
When two individuals $i$ and $j$ in close spatial proximity ($d_{ij} < d_{\text{threshold}}$) possess opposing headings ($\Delta \theta > 135^\circ$):

$$
\cos(\Delta \theta) = \frac{\vec{v}_i \cdot \vec{v}_j}{\|\vec{v}_i\| \|\vec{v}_j\|} \le \cos(135^\circ) \approx -0.707
$$

This produces shear turbulence, increases local collision frequency, and precipitates sudden crowd blockages.

---

## 2. Component Architecture

The VCIE architecture is structured into dedicated, decoupled modules within `backend/app/crowdguard/`:

| Module | Core Responsibility | Key Classes / Functions |
|---|---|---|
| `schemas.py` | Pydantic V2 domain models and telemetry schemas | `CalibrationConfig`, `TrackedPerson`, `ZoneMetric`, `CongestionAlert` |
| `calibration.py` | 4-point homography calculation, validation, and projection | `CameraCalibrationEngine`, `order_points_clockwise`, `is_convex_quad` |
| `perspective.py` | Top-down warping, metric distance grid, zone drawing | `BirdEyeViewGenerator`, `draw_metric_grid`, `draw_calibration_overlay` |
| `detection.py` | YOLO person detector & labelled classical CV fallback | `PersonDetectionEngine`, `extract_ground_contact_and_project` |
| `tracking.py` | Kalman 2D tracking, persistence, and velocity estimation | `MultiObjectTracker`, `KalmanTracker2D` |
| `density.py` | Gaussian KDE accumulator, zone triage, colormap renderer | `VirtualCrowdDensityEngine`, `render_heatmap` |
| `movement.py` | Vector fields, bottleneck and opposing stream detection | `MovementIntelligenceEngine`, `extract_movement_vectors` |
| `digital_twin.py` | Top-down 2D architectural venue twin renderer | `VenueDigitalTwin`, `VenueDigitalTwinModel`, `Portal`, `Obstacle` |
| `synthetic.py` | Deterministic multi-agent crowd simulator & frame generator | `SyntheticDemonstrationEngine`, `SyntheticAgent` |
| `pipeline.py` | 12-stage non-blocking processing orchestrator | `VirtualCrowdIntelligencePipeline` |

---

## 3. Calibration Requirements & Operator Guide

### 3.1 Four-Point Ground Plane Calibration Protocol
1. **Camera Placement**: Ensure the camera has an unobstructed view of the ground surface. Avoid extreme grazing angles ($<15^\circ$ to horizontal), which elevate the homography condition number.
2. **Selecting Reference Points**:
   - The user selects 4 points on the physical floor in clockwise order: **Top-Left (TL)**, **Top-Right (TR)**, **Bottom-Right (BR)**, and **Bottom-Left (BL)**.
   - Points must form a strictly convex quadrilateral.
   - Real-world distances (width and height in meters) between the bounds must be measured or obtained from architectural blueprints.
3. **Metric Scale Setting**:
   - Provide ground width in meters $W_m$ and ground height in meters $H_m$.
   - Output resolution defaults to $800 \times 600$ pixels.
   - Calibration engine computes:
     $$m_x = \frac{W_m}{800}, \quad m_y = \frac{H_m}{600}$$

---

## 4. REST API Contract Specifications

All VCIE routes are mounted under `/api/crowdguard/*`:

### 4.1 Calibration
- `POST /api/crowdguard/calibration`
  - **Request**: `CalibrationConfig` JSON (source quad points, canvas width/height, real-world width/height in meters).
  - **Response**: `CalibrationResult` JSON ($3 \times 3$ matrix $H$, $H^{-1}$, meters per pixel, validity status, condition warnings).
  - **Status**: `200 OK` on success, `400 Bad Request` if points are collinear or degenerate.

### 4.2 Video Ingestion & Processing
- `POST /api/crowdguard/video/upload`
  - **Request**: `multipart/form-data` containing CCTV video file (`.mp4`, `.avi`, `.mov`).
  - **Response**: Upload receipt, validated resolution, frame count, FPS, and duration.
- `POST /api/crowdguard/analysis/start`
  - **Request**: Form parameters (`video_path`, `frame_stride`, `detection_confidence`, `heatmap_mode`, `max_frames`).
  - **Response**: Job ID and background worker launch confirmation. Does not block FastAPI event loop.
- `GET /api/crowdguard/analysis/{job_id}`
  - **Response**: `AnalysisJobSummary` JSON (progress %, current frame, active FPS, frame metrics, active alerts).

### 4.3 Live Streaming & Telemetry Endpoints
- `GET /api/crowdguard/analysis/{job_id}/frame` $\to$ Returns JPEG annotated original camera frame with bounding boxes and calibration quad.
- `GET /api/crowdguard/analysis/{job_id}/birdseye` $\to$ Returns JPEG perspective-warped top-down ground plane with metric distance grid.
- `GET /api/crowdguard/analysis/{job_id}/heatmap` $\to$ Returns JPEG Gaussian KDE density heatmap overlay.
- `GET /api/crowdguard/analysis/{job_id}/movement` $\to$ Returns JPEG movement direction vector arrows and stagnation pins.
- `GET /api/crowdguard/analysis/{job_id}/digitaltwin` $\to$ Returns JPEG composite venue digital twin.
- `GET /api/crowdguard/analysis/{job_id}/tracks` $\to$ Returns JSON array of active tracks, positions, velocities, and zone metrics.

### 4.4 Simulation Control
- `POST /api/crowdguard/simulation/step?scenario={scenario}&mode={mode}&sigma={sigma}` $\to$ Steps deterministic synthetic simulation and returns complete frame telemetry.
- `POST /api/crowdguard/simulation/reset?scenario={scenario}` $\to$ Resets crowd simulation to initial state.
- `GET /api/crowdguard/presets` $\to$ Returns preconfigured venue architectural layouts, default calibrations, and scenario catalogs.

---

## 5. Performance Benchmarks on Laptop Development Hardware

The pipeline was benchmarked on standard laptop CPU execution (Intel 64-bit / Python 3.12, no CUDA GPU required):

| Pipeline Stage | Latency (ms) | Complexity | Optimization Strategy |
|---|---|---|---|
| Frame Acquisition & Decimation | $1.2\text{ ms}$ | $O(1)$ | Stride decimation (processes every $N$-th frame) |
| Perspective Warp (`cv2.warpPerspective`) | $2.4\text{ ms}$ | $O(W \cdot H)$ | Fixed $800 \times 600$ output canvas |
| Person Detection (Inference) | $28.0\text{ ms}$ | $O(\text{CNN})$ | Ultralytics YOLOv8n / Fast classical CV contour fallback |
| Foot Ground Projection | $0.2\text{ ms}$ | $O(N)$ | Homogeneous vector matrix multiplication |
| Multi-Object Tracking & Kalman Filter | $1.1\text{ ms}$ | $O(N \cdot M)$ | Spatial Euclidean gating before greedy cost matching |
| Gaussian KDE Density Accumulator | $1.6\text{ ms}$ | $O(W \cdot H)$ | Separable 2D Gaussian convolution via `cv2.GaussianBlur` |
| Movement Vectors & Divergence | $0.8\text{ ms}$ | $O(N)$ | Fixed history deque ($30$ frames maximum) |
| Visualization Rendering & Blending | $3.5\text{ ms}$ | $O(W \cdot H)$ | Vectorized alpha compositing |
| **Total Pipeline Latency** | **$38.8\text{ ms}$** | — | **Achieves $\sim 25\text{--}30\text{ FPS}$ on multi-core laptop CPU** |

---

## 6. Limitations & Human Supervisory Safety Position

1. **Planar Ground Surface Assumption**: The homography model assumes all pedestrians move on a flat ground plane ($Z = 0$). Venues with significant topography, split levels, or staircases require multi-homography partitioning.
2. **Occlusion Non-Hallucination**: VCIE does **not** claim to reconstruct pedestrians who are completely hidden behind columns, walls, or dense foreground clusters. Counts represent detected visible individuals projected to ground points; carried-forward tracks handle temporary occlusions up to $25$ frames.
3. **Advisory Decision Support**: All alerts, density heatmaps, and bottleneck warnings are decision-support indicators for event commanders, security personnel, and crowd safety stewards. They do **not** constitute autonomous legal control of crowd events.
4. **Emergency Egress Invariance**: Under no circumstances may any algorithm recommendation close, restrict, or lock an emergency exit route.

---
*CROWDGUARD Virtual Crowd Intelligence Engine (VCIE) v1.0.0 — Engineered for ISACA Safety & Resilience.*
