"""Virtual Crowd Intelligence Engine (VCIE) Pipeline.

Orchestrates the entire computer vision and crowd intelligence workflow:
Camera Ingestion -> Perspective Calibration -> Person Detection -> Tracking ->
Bird's-Eye Coordinate Projection -> Gaussian KDE Density -> Movement Analysis -> Digital Twin.
Optimized for laptop CPU execution with configurable frame decimation and benchmarking.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np

from .calibration import CameraCalibrationEngine
from .crowd_detection import Detection
from .crowd_tracking import build_tracker
from .density import VirtualCrowdDensityEngine
from .detection import PersonDetectionEngine
from .movement import MovementIntelligenceEngine
from .perspective import BirdEyeViewGenerator
from .schemas import (
    AnalysisJobSummary,
    BoundingBox,
    CalibrationConfig,
    FrameAnalysisResult,
    HeatmapMode,
    VideoProcessingConfig,
    ZoneDefinition,
)
from .synthetic import SyntheticDemonstrationEngine
from .tracking import MultiObjectTracker
from .venue import VenueDigitalTwin

logger = logging.getLogger(__name__)


class VirtualCrowdIntelligencePipeline:
    """Integrated engine pipeline orchestrating detection, tracking, density, and flow analysis."""

    def __init__(
        self,
        calibration_config: Optional[CalibrationConfig] = None,
        processing_config: Optional[VideoProcessingConfig] = None,
        zones: Optional[List[ZoneDefinition]] = None,
        identity_tracking: bool = True,
    ):
        self.config = processing_config or VideoProcessingConfig()
        self.lock = threading.RLock()  # one frame at a time; renders and reads see a consistent state
        self.identity_tracking = identity_tracking
        self._identity_tracker = None
        self.last_identity_objects: list = []
        self.last_raw_boxes: list = []
        self.identity_tracker_info: dict[str, Any] = {"tracker": "ground-plane kalman (distance association)"}

        # 1. Calibration Engine
        self.calibration = CameraCalibrationEngine(calibration_config)

        # 2. Bird's-Eye View Generator
        self.perspective = BirdEyeViewGenerator(self.calibration)

        # 3. Person Detection Engine
        self.detector = PersonDetectionEngine(
            calibration=self.calibration,
            confidence_threshold=self.config.detection_confidence,
            use_fallback_if_missing=True,
        )

        # 4. Multi-Object Tracker
        self.tracker = MultiObjectTracker(
            calibration=self.calibration,
            max_age_frames=self.config.track_history_length,
            min_hits=2,
            max_history_length=self.config.track_history_length,
        )

        # 5. Density Engine
        self.density_engine = VirtualCrowdDensityEngine(
            calibration=self.calibration,
            bandwidth_sigma=self.config.kde_bandwidth_sigma,
        )

        # 6. Movement Intelligence Engine
        self.movement_engine = MovementIntelligenceEngine(
            calibration=self.calibration,
        )

        # 7. Venue Digital Twin
        self.venue = VenueDigitalTwin()
        self.zones = zones or self.venue.model.zones

        # Synthetic demonstration engine
        self.synthetic_engine = SyntheticDemonstrationEngine(self.calibration)

        # Performance telemetry
        self.last_latency_ms: float = 0.0
        self.fps: float = 0.0
        self._frame_count: int = 0
        self._start_time: float = time.time()

        # Cached latest frame outputs for API streaming
        self.latest_camera_frame: Optional[np.ndarray] = None
        self.latest_birdseye_frame: Optional[np.ndarray] = None
        self.latest_heatmap_frame: Optional[np.ndarray] = None
        self.latest_movement_frame: Optional[np.ndarray] = None
        self.latest_digital_twin_frame: Optional[np.ndarray] = None
        self.latest_result: Optional[FrameAnalysisResult] = None

    def process_frame(
        self,
        frame: np.ndarray,
        frame_idx: int = 0,
        timestamp_s: float = 0.0,
        is_synthetic: bool = False,
        synthetic_boxes: Optional[List[BoundingBox]] = None,
        render: bool = True,
        source_kind: Optional[str] = None,
    ) -> FrameAnalysisResult:
        """Processes a single camera video frame through the complete VCIE pipeline.

        `render=False` skips the four visual renders (used for non-key frames of batch jobs).
        """
        with self.lock:
            return self._process_frame(frame, frame_idx, timestamp_s, is_synthetic, synthetic_boxes, render, source_kind)

    def _identity(self, frame_rate: float):
        if self._identity_tracker is None and self.identity_tracking:
            self._identity_tracker, info = build_tracker("auto", frame_rate=frame_rate)
            self.identity_tracker_info = {**info, "kinematics": "ground-plane Kalman filter"}
        return self._identity_tracker

    def _process_frame(self, frame, frame_idx, timestamp_s, is_synthetic, synthetic_boxes, render, source_kind) -> FrameAnalysisResult:
        t0 = time.perf_counter()
        self._frame_count += 1

        # 1. Resize input frame if needed to bound latency on laptop CPUs
        h, w = frame.shape[:2]
        if w > self.config.max_resolution_width:
            scale = self.config.max_resolution_width / float(w)
            target_dim = (self.config.max_resolution_width, int(round(h * scale)))
            proc_frame = cv2.resize(frame, target_dim, interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame.copy()

        # 2. Warp frame to bird's-eye view using calibrated homography (only when rendering)
        birdseye_with_grid = self.perspective.draw_metric_grid(self.perspective.warp_frame(proc_frame)) if render else None

        # 3. Person Detection (synthetic scenarios use their ground-truth boxes: no detector involved)
        detection_failed = False
        self.last_raw_boxes = []
        if is_synthetic and synthetic_boxes is not None:
            raw_boxes = synthetic_boxes
        else:
            try:
                raw_boxes = self.detector.detect(proc_frame, confidence_threshold=self.config.detection_confidence)
            except Exception as exc:  # noqa: BLE001 - a failed detection is recorded, never treated as an empty scene
                logger.warning("Detection failed on frame %s: %s", frame_idx, exc)
                raw_boxes, detection_failed = [], True
        self.last_raw_boxes = raw_boxes

        # 4/5. Identity (ByteTrack in image space for real footage) + ground-plane projection + Kalman kinematics
        ids: Optional[List[int]] = None
        identity = None if (is_synthetic or detection_failed) else self._identity(10.0)
        self.last_identity_objects = []
        if identity is not None:
            tracked = identity.update([Detection(b.x1, b.y1, b.x2, b.y2, b.confidence) for b in raw_boxes], timestamp_s)
            # Image-space identities (all of them, including people outside the calibrated ground quad)
            self.last_identity_objects = tracked
            id_boxes = [(o.track_id, BoundingBox(x1=o.box[0], y1=o.box[1], x2=o.box[2], y2=o.box[3],
                                                 confidence=round(min(1.0, max(0.0, o.confidence)), 4)))
                        for o in tracked if o.confirmed]
            projected_detections, ids = [], []
            for tid, box in id_boxes:
                proj = self.detector.extract_ground_contact_and_project([box])
                if proj:
                    projected_detections.append(proj[0])
                    ids.append(tid)
        else:
            projected_detections = self.detector.extract_ground_contact_and_project(raw_boxes)

        if detection_failed:
            tracks = self.tracker.update([], frame_idx=frame_idx, timestamp_s=timestamp_s)
        else:
            tracks = self.tracker.update(projected_detections, frame_idx=frame_idx, timestamp_s=timestamp_s, external_ids=ids)

        # 6. Crowd Density Estimation (Gaussian KDE)
        density_grid = self.density_engine.compute_density_grid(
            tracks=tracks,
            bandwidth_sigma=self.config.kde_bandwidth_sigma,
            weight_by_inversed_speed=(self.config.heatmap_mode == HeatmapMode.MOVEMENT),
        )

        # 7. Zone Analytics
        zone_metrics = self.density_engine.evaluate_zones(tracks, self.zones)

        # 8. Movement Vector Analysis & Alerts
        movement_vectors = self.movement_engine.extract_movement_vectors(tracks)
        alerts = self.movement_engine.analyze_congestion_and_alerts(
            tracks=tracks,
            zone_metrics=zone_metrics,
            density_grid=density_grid,
            timestamp_s=timestamp_s,
        )

        if render:
            self._render(proc_frame, birdseye_with_grid, tracks, zone_metrics, movement_vectors)

        # Calculate density statistics
        peak_density = float(np.max(density_grid)) if density_grid.size > 0 else 0.0
        mean_density = float(np.mean(density_grid)) if density_grid.size > 0 else 0.0
        res = self.calibration.result
        pixel_area = (res.meters_per_pixel_x * res.meters_per_pixel_y) if (res and res.meters_per_pixel_x and res.meters_per_pixel_y) else 0.001
        high_density_m2 = np.count_nonzero(density_grid >= 1.5) * pixel_area
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self.last_latency_ms = round(latency_ms, 1)
        elapsed = time.time() - self._start_time
        self.fps = round(self._frame_count / max(0.1, elapsed), 1)
        result = FrameAnalysisResult(
            frame_idx=frame_idx, timestamp_s=round(timestamp_s, 2), total_detected=len(raw_boxes),
            active_tracks_count=len(tracks), tracks=tracks, movement_vectors=movement_vectors, zone_metrics=zone_metrics,
            peak_density_per_sq_meter=round(peak_density, 2), mean_density_per_sq_meter=round(mean_density, 3),
            high_density_area_sq_meters=round(high_density_m2, 1), alerts=alerts, processing_latency_ms=self.last_latency_ms,
            is_fallback_detection=(not is_synthetic) and self.detector.use_fallback, is_synthetic=is_synthetic,
            source_kind=source_kind or ("synthetic" if is_synthetic else "recorded_video"),
            detector_backend="synthetic ground truth" if is_synthetic else self.detector.backend,
            detection_failed=detection_failed,
            tracker=self.identity_tracker_info.get("tracker", "ground-plane kalman") if not is_synthetic else "ground-plane kalman (distance association)",
        )
        self.latest_result = result
        return result

    def _render(self, proc_frame, birdseye_with_grid, tracks, zone_metrics, movement_vectors) -> None:
        """Render the five synchronised views of one frame and cache them together."""
        annotated_cam = self.perspective.draw_calibration_overlay_on_camera(proc_frame)
        for trk in tracks:
            b = trk.camera_bbox
            cv2.rectangle(annotated_cam, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), (0, 255, 120), 2)
            cv2.circle(annotated_cam, (int(trk.camera_ground_point[0]), int(trk.camera_ground_point[1])), 4, (0, 215, 255), -1)
            cv2.putText(annotated_cam, f"#{trk.track_id}", (int(b.x1), max(15, int(b.y1) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # Heatmap overlay on bird's-eye view
        heatmap_frame = self.density_engine.render_heatmap(
            base_image=birdseye_with_grid,
            tracks=tracks,
            zones=self.zones,
            mode=self.config.heatmap_mode,
            bandwidth_sigma=self.config.kde_bandwidth_sigma,
        )

        # Movement vectors overlay on bird's-eye view
        movement_frame = self.movement_engine.draw_movement_overlay(birdseye_with_grid, movement_vectors)

        # Venue digital twin rendering
        dt_frame = self.venue.render_digital_twin_with_telemetry(
            tracks=tracks,
            zone_metrics=zone_metrics,
            movement_vectors=movement_vectors,
            heatmap_overlay=heatmap_frame,
            is_schematic=False,
            base_camera_warped=birdseye_with_grid,
        )

        # Cache frames
        self.latest_camera_frame = annotated_cam
        self.latest_birdseye_frame = birdseye_with_grid
        self.latest_heatmap_frame = heatmap_frame
        self.latest_movement_frame = movement_frame
        self.latest_digital_twin_frame = dt_frame

    def render_bundle(self, max_width: int = 640, quality: int = 72) -> dict[str, Any]:
        """The five views of the SAME frame as base64 JPEG data URLs (keeps the UI synchronised)."""
        with self.lock:
            views = {"camera": self.latest_camera_frame, "birdseye": self.latest_birdseye_frame,
                     "heatmap": self.latest_heatmap_frame, "movement": self.latest_movement_frame,
                     "digital_twin": self.latest_digital_twin_frame}
            out: dict[str, Any] = {"frame_idx": self.latest_result.frame_idx if self.latest_result else None}
            for name, img in views.items():
                if img is None:
                    out[name] = None
                    continue
                h, w = img.shape[:2]
                if w > max_width:
                    img = cv2.resize(img, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                out[name] = ("data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")) if ok else None
            return out

    def step_synthetic(self, scenario: str = "plaza_normal", dt: float = 0.1) -> FrameAnalysisResult:
        """Generates a synthetic frame and runs it through the full pipeline."""
        if self.synthetic_engine.scenario_name != scenario:
            self.synthetic_engine._init_scenario(scenario)

        self.synthetic_engine.step(dt=dt)
        cam_frame, gt_boxes = self.synthetic_engine.generate_frame()
        t_sec = self.synthetic_engine.current_frame * dt

        return self.process_frame(
            frame=cam_frame,
            frame_idx=self.synthetic_engine.current_frame,
            timestamp_s=t_sec,
            is_synthetic=True,
            synthetic_boxes=gt_boxes,
        )

    def process_video_file(
        self,
        video_path: str,
        max_frames: int = 300,
        progress_callback: Optional[Callable[[AnalysisJobSummary], None]] = None,
    ) -> List[FrameAnalysisResult]:
        """Asynchronously processes a video file with frame decimation."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"Could not open video: {video_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
        results: List[FrameAnalysisResult] = []

        frame_idx = 0
        processed_count = 0

        try:
            while cap.isOpened() and processed_count < max_frames:
                ret, frame = cap.read()
                if not ret:
                    break

                # Frame skipping / decimation according to frame_stride
                if frame_idx % self.config.frame_stride == 0:
                    t_sec = frame_idx / fps_in
                    res = self.process_frame(frame, frame_idx=frame_idx, timestamp_s=t_sec, is_synthetic=False)
                    results.append(res)
                    processed_count += 1

                    if progress_callback:
                        progress = min(100.0, (frame_idx / max(1, total_frames)) * 100.0)
                        summary = AnalysisJobSummary(
                            job_id="batch-job",
                            status="running",
                            progress_pct=round(progress, 1),
                            current_frame=frame_idx,
                            total_frames=total_frames,
                            fps=self.fps,
                            latest_metrics=res,
                            created_at=str(time.time()),
                        )
                        progress_callback(summary)

                frame_idx += 1
        finally:
            cap.release()

        return results
