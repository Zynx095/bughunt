"""CROWDGUARD Virtual Crowd Intelligence Engine (VCIE).

Transforms conventional oblique camera video into virtual top-down bird's-eye crowd intelligence
maps with Gaussian kernel density estimation, movement vector tracking, and digital twin analytics.
"""
from __future__ import annotations

from .calibration import CameraCalibrationEngine
from .density import VirtualCrowdDensityEngine
from .detection import PersonDetectionEngine
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
from .venue import VenueDigitalTwin, VenueDigitalTwinModel

__version__ = "1.0.0"
__all__ = [
    "CameraCalibrationEngine",
    "BirdEyeViewGenerator",
    "PersonDetectionEngine",
    "VirtualCrowdDensityEngine",
    "MovementIntelligenceEngine",
    "VirtualCrowdIntelligencePipeline",
    "VenueDigitalTwin",
    "VenueDigitalTwinModel",
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
]
