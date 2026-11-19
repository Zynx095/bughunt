"""Virtual Crowd Intelligence Engine (VCIE) Pipeline.

Orchestrates the entire computer vision and crowd intelligence workflow:
Camera Ingestion -> Perspective Calibration -> Person Detection -> Tracking ->
Bird's-Eye Coordinate Projection -> Gaussian KDE Density -> Movement Analysis -> Digital Twin.
Optimized for laptop CPU execution with configurable frame decimation and benchmarking.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Dict, List, Optional, Tuple
import cv2
import numpy as np

from .calibration import CameraCalibrationEngine
from .density import VirtualCrowdDensityEngine
from .detection import PersonDetectionEngine
from .movement import MovementIntelligenceEngine
from .perspective import BirdEyeViewGenerator
from .schemas import (
    AnalysisJobSummary,
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
    ):
        self.config = processing_config or VideoProcessingConfig()

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
    ) -> FrameAnalysisResult:
        """Processes a single camera video frame through the complete 12-stage VCIE pipeline.
        
        Returns:
            Structured FrameAnalysisResult with all metrics, tracks, and alerts.
        """
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

        # 2. Warp frame to bird's-eye view using calibrated homography
        birdseye_base = self.perspective.warp_frame(proc_frame)
        # Apply metric grid overlay
        birdseye_with_grid = self.perspective.draw_metric_grid(birdseye_base)

        # 3. Person Detection
        if is_synthetic and synthetic_boxes is not None:
            raw_boxes = synthetic_boxes
        else:
            raw_boxes = self.detector.detect(proc_frame, confidence_threshold=self.config.detection_confidence)

        # 4. Extract ground contact points & project to bird's-eye canvas
        projected_detections = self.detector.extract_ground_contact_and_project(raw_boxes)

        # 5. Multi-Object Tracking & Velocity Estimation
        tracks = self.tracker.update(projected_detections, frame_idx=frame_idx, timestamp_s=timestamp_s)

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

        # 9. Render Visual Visualizations for Cache & API Streaming
        # Camera view with bounding boxes and calibration quad
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

        # Calculate density statistics
        peak_density = float(np.max(density_grid)) if density_grid.size > 0 else 0.0
        mean_density = float(np.mean(density_grid)) if density_grid.size > 0 else 0.0

        # Physical high density area in m^2
        res = self.calibration.result
        pixel_area = (res.meters_per_pixel_x * res.meters_per_pixel_y) if (res and res.meters_per_pixel_x and res.meters_per_pixel_y) else 0.001
        high_density_pixels = np.count_nonzero(density_grid >= 1.5)
        high_density_m2 = high_density_pixels * pixel_area

        latency_ms = (time.perf_counter() - t0) * 1000.0
        self.last_latency_ms = round(latency_ms, 1)

        elapsed = time.time() - self._start_time
        self.fps = round(self._frame_count / max(0.1, elapsed), 1)

        result = FrameAnalysisResult(
            frame_idx=frame_idx,
            timestamp_s=round(timestamp_s, 2),
            total_detected=len(raw_boxes),
            active_tracks_count=len(tracks),
            tracks=tracks,
            movement_vectors=movement_vectors,
            zone_metrics=zone_metrics,
            peak_density_per_sq_meter=round(peak_density, 2),
            mean_density_per_sq_meter=round(mean_density, 3),
            high_density_area_sq_meters=round(high_density_m2, 1),
            alerts=alerts,
            processing_latency_ms=self.last_latency_ms,
            is_fallback_detection=self.detector.use_fallback,
            is_synthetic=is_synthetic,
        )

        # Cache frames
        self.latest_camera_frame = annotated_cam
        self.latest_birdseye_frame = birdseye_with_grid
        self.latest_heatmap_frame = heatmap_frame
        self.latest_movement_frame = movement_frame
        self.latest_digital_twin_frame = dt_frame
        self.latest_result = result

        return result

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
