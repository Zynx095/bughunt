"""Pydantic schemas and data models for CrowdGuard Virtual Crowd Intelligence Engine (VCIE)."""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, Field


class CalibrationPoint(BaseModel):
    """A 2D point in pixel space."""
    x: float = Field(..., description="X coordinate in pixels")
    y: float = Field(..., description="Y coordinate in pixels")

    def to_tuple(self) -> Tuple[float, float]:
        return (float(self.x), float(self.y))


class CalibrationQuad(BaseModel):
    """Four ordered reference points on the camera ground plane: TL, TR, BR, BL."""
    top_left: CalibrationPoint
    top_right: CalibrationPoint
    bottom_right: CalibrationPoint
    bottom_left: CalibrationPoint

    def to_list(self) -> List[Tuple[float, float]]:
        return [
            self.top_left.to_tuple(),
            self.top_right.to_tuple(),
            self.bottom_right.to_tuple(),
            self.bottom_left.to_tuple(),
        ]


class CalibrationConfig(BaseModel):
    """Configuration for ground plane homography calibration."""
    source_points: CalibrationQuad
    target_width_px: int = Field(800, ge=100, le=4096, description="Bird's-eye canvas width in pixels")
    target_height_px: int = Field(600, ge=100, le=4096, description="Bird's-eye canvas height in pixels")
    ground_width_meters: Optional[float] = Field(20.0, gt=0.1, le=1000.0, description="Real world ground plane width in meters")
    ground_height_meters: Optional[float] = Field(15.0, gt=0.1, le=1000.0, description="Real world ground plane height in meters")
    venue_name: str = Field("Default Monitored Zone", description="Name of the calibrated venue area")


class CalibrationResult(BaseModel):
    """Result of homography calculation and validation."""
    valid: bool
    homography_matrix: Optional[List[List[float]]] = None
    inverse_homography_matrix: Optional[List[List[float]]] = None
    target_width_px: int
    target_height_px: int
    meters_per_pixel_x: Optional[float] = None
    meters_per_pixel_y: Optional[float] = None
    ground_area_sq_meters: Optional[float] = None
    condition_number: Optional[float] = None
    message: str = "Calibration calculated successfully"
    warnings: List[str] = Field(default_factory=list)


class BoundingBox(BaseModel):
    """2D bounding box in original camera frame coordinates [x1, y1, x2, y2]."""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    class_name: str = "person"

    @property
    def ground_contact_point(self) -> Tuple[float, float]:
        """Calculates bottom-centre coordinate representing foot/ground contact point."""
        return ((self.x1 + self.x2) / 2.0, self.y2)


class TrackPoint(BaseModel):
    """Historical position record."""
    frame_idx: int
    timestamp_s: float
    camera_x: float
    camera_y: float
    birdseye_x: float
    birdseye_y: float
    speed_mps: float = 0.0


class TrackedPerson(BaseModel):
    """Tracked person state across sequential frames."""
    track_id: int
    camera_bbox: BoundingBox
    camera_ground_point: Tuple[float, float]
    birdseye_point: Tuple[float, float]
    world_pos_meters: Optional[Tuple[float, float]] = None
    velocity_vector_px: Tuple[float, float] = (0.0, 0.0)
    velocity_vector_mps: Optional[Tuple[float, float]] = None
    speed_mps: float = 0.0
    heading_deg: float = 0.0
    confidence: float = 1.0
    age_frames: int = 1
    zone_id: Optional[str] = None
    history: List[TrackPoint] = Field(default_factory=list)


class HeatmapMode(str, Enum):
    GAUSSIAN = "gaussian"
    POINT = "point"
    ZONE = "zone"
    MOVEMENT = "movement"


class DensityRiskLevel(str, Enum):
    LOW = "low"            # < 0.5 persons/m^2
    MODERATE = "moderate"  # 0.5 - 1.5 persons/m^2
    HIGH = "high"          # 1.5 - 3.0 persons/m^2
    CRITICAL = "critical"  # > 3.0 persons/m^2


class ZoneDefinition(BaseModel):
    """Geometrical zone in bird's-eye canvas (polygon or rect)."""
    id: str
    name: str
    polygon: List[Tuple[float, float]] = Field(..., description="Ordered vertices in bird's-eye pixels")
    capacity: int = Field(50, gt=0)
    area_sq_meters: Optional[float] = 100.0
    risk_threshold_high: float = 1.5   # persons/m^2
    risk_threshold_critical: float = 3.0 # persons/m^2


class ZoneMetric(BaseModel):
    """Real-time zone analytics."""
    zone_id: str
    zone_name: str
    population: int
    capacity: int
    occupancy_pct: float
    area_sq_meters: float
    density_per_sq_meter: float
    avg_speed_mps: float
    risk_level: DensityRiskLevel
    status_message: str


class CongestionAlert(BaseModel):
    """Safety and congestion warning."""
    id: str
    timestamp_s: float
    alert_type: str = Field(..., description="bottleneck | opposing_flow | sudden_accumulation | severe_density")
    severity: str = Field(..., description="low | moderate | high | critical")
    zone_id: Optional[str] = None
    message: str
    location_birdseye: Tuple[float, float]
    metrics: dict[str, Any] = Field(default_factory=dict)
    recommendation: str


class MovementVector(BaseModel):
    """Vector representation for top-down crowd flow."""
    track_id: int
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    speed_mps: float
    heading_deg: float
    risk_indicator: Optional[str] = None


class FrameAnalysisResult(BaseModel):
    """Complete analysis output for a single video frame."""
    frame_idx: int
    timestamp_s: float
    total_detected: int
    active_tracks_count: int
    tracks: List[TrackedPerson]
    movement_vectors: List[MovementVector]
    zone_metrics: List[ZoneMetric]
    peak_density_per_sq_meter: float
    mean_density_per_sq_meter: float
    high_density_area_sq_meters: float
    alerts: List[CongestionAlert]
    processing_latency_ms: float
    is_fallback_detection: bool = False
    is_synthetic: bool = False
    # Provenance: "synthetic" (simulated agents, ground-truth boxes) | "recorded_video" | "image" | "live_camera"
    source_kind: str = "recorded_video"
    detector_backend: str = "none"
    detection_failed: bool = False
    tracker: str = "ground-plane kalman"


class VideoProcessingConfig(BaseModel):
    """Configuration for processing video streams or files."""
    frame_stride: int = Field(2, ge=1, le=30, description="Process every Nth frame")
    max_resolution_width: int = Field(1280, ge=320, le=3840)
    detection_confidence: float = Field(0.35, ge=0.05, le=0.95)
    kde_bandwidth_sigma: float = Field(25.0, ge=5.0, le=100.0, description="Gaussian KDE kernel radius in pixels")
    heatmap_mode: HeatmapMode = HeatmapMode.GAUSSIAN
    track_history_length: int = Field(30, ge=5, le=120)
    enable_bottleneck_detection: bool = True
    enable_opposing_flow_detection: bool = True


class AnalysisJobSummary(BaseModel):
    """Summary of completed or running analysis."""
    job_id: str
    status: str = Field("pending", description="pending | running | completed | failed")
    progress_pct: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    fps: float = 0.0
    latest_metrics: Optional[FrameAnalysisResult] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
