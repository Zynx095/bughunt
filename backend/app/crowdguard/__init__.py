"""CROWDGUARD Virtual Crowd Intelligence Engine (VCIE) & Crowd Safety Monitoring Services.

Transforms conventional oblique camera video into virtual top-down bird's-eye crowd intelligence
maps with Gaussian kernel density estimation, movement vector tracking, and digital twin analytics.
Also provides core venue models and crowd safety services.

Safety position (applies to every module):
  * Counts are estimates, never ground truth. Occlusion and tracking errors are modelled explicitly.
  * A missing or stale feed is *unknown*, never zero.
  * Outputs are advisory. Human organisers make every intervention decision.
  * No software recommendation may close or restrict an emergency exit.
"""
from __future__ import annotations

# VCIE Computer Vision Modules
from .calibration import CameraCalibrationEngine
from .density import VirtualCrowdDensityEngine
from .detection import PersonDetectionEngine
from .digital_twin import Obstacle, Portal, VenueDigitalTwin, VenueDigitalTwinModel
from .movement import MovementIntelligenceEngine
from .perspective import BirdEyeViewGenerator
from .pipeline import VirtualCrowdIntelligencePipeline
from .schemas import (
    AnalysisJobSummary,
    BoundingBox,
    CalibrationConfig,
    CalibrationPoint,
    CalibrationQuad,
    CalibrationResult,
    CongestionAlert,
    DensityRiskLevel,
    FrameAnalysisResult,
    HeatmapMode,
    MovementVector,
    TrackedPerson,
    TrackPoint,
    VideoProcessingConfig,
    ZoneDefinition,
    ZoneMetric,
)
from .synthetic import SyntheticDemonstrationEngine
from .venue import Venue, load_venue, sample_venue_config

__version__ = "1.0.0"
__all__ = [
    # VCIE exports
    "CameraCalibrationEngine",
    "BirdEyeViewGenerator",
    "PersonDetectionEngine",
    "VirtualCrowdDensityEngine",
    "MovementIntelligenceEngine",
    "VirtualCrowdIntelligencePipeline",
    "VenueDigitalTwin",
    "VenueDigitalTwinModel",
    "Portal",
    "Obstacle",
    "SyntheticDemonstrationEngine",
    "CalibrationConfig",
    "CalibrationPoint",
    "CalibrationQuad",
    "CalibrationResult",
    "BoundingBox",
    "TrackedPerson",
    "TrackPoint",
    "HeatmapMode",
    "DensityRiskLevel",
    "ZoneDefinition",
    "ZoneMetric",
    "CongestionAlert",
    "MovementVector",
    "FrameAnalysisResult",
    "VideoProcessingConfig",
    "AnalysisJobSummary",
    # Core Venue exports
    "Venue",
    "load_venue",
    "sample_venue_config",
]
