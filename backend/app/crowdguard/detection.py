"""Calibration-aware person detection for the Virtual Crowd Intelligence Engine (VCIE).

There is exactly ONE detector implementation in CROWDGUARD: `crowd_detection.py` (local YOLO weights,
never downloaded, with a labelled OpenCV-HOG fallback and verified status). This module only adapts it
to the VCIE data model: it converts detections into `BoundingBox` objects and projects each person's
ground-contact point (bottom-centre of the box) onto the calibrated bird's-eye plane.
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional, Tuple

import numpy as np

from .calibration import CameraCalibrationEngine
from .crowd_detection import get_detector
from .schemas import BoundingBox

logger = logging.getLogger(__name__)


class PersonDetectionEngine:
    """Detects people in camera frames and estimates their ground-plane positions."""

    def __init__(
        self,
        calibration: CameraCalibrationEngine,
        model_name: str | None = None,
        confidence_threshold: float = 0.35,
        use_fallback_if_missing: bool = True,
        preference: str | None = None,
    ):
        self.calib = calibration
        self.confidence_threshold = confidence_threshold
        # The shared, cached detector (the model is loaded once per process).
        preference = preference or os.getenv("CROWDGUARD_DETECTOR", "auto")
        self._detector, self.status = get_detector(preference if use_fallback_if_missing else "yolo", model_name)
        self.backend: str = self.status.get("backend", "none")
        self.available: bool = self._detector is not None
        # True whenever the neural detector is not in use (HOG fallback or no detector at all).
        self.use_fallback: bool = self.backend != "yolo"
        self.last_error: Optional[str] = None

    def describe(self) -> dict[str, Any]:
        return {"backend": self.backend, "available": self.available, "verified": self.status.get("verified", False),
                "model": self.status.get("model"), "fallback": self.use_fallback, "limitation": self.status.get("limitation")}

    def detect(self, frame: np.ndarray, confidence_threshold: Optional[float] = None) -> List[BoundingBox]:
        """Detect people in a BGR frame. Raises RuntimeError when no detector is available, so callers
        record a *detection failure* instead of an empty scene."""
        if self._detector is None:
            self.last_error = self.status.get("reason", "no person detector available")
            raise RuntimeError(self.last_error)
        thresh = self.confidence_threshold if confidence_threshold is None else confidence_threshold
        boxes: List[BoundingBox] = []
        for d in self._detector.detect(frame):
            if d.confidence >= thresh:
                boxes.append(BoundingBox(x1=d.x1, y1=d.y1, x2=d.x2, y2=d.y2,
                                         confidence=round(min(1.0, max(0.0, d.confidence)), 4), class_name="person"))
        return boxes

    def extract_ground_contact_and_project(
        self,
        boxes: List[BoundingBox],
        clip_to_birdseye_bounds: bool = True,
    ) -> List[Tuple[BoundingBox, Tuple[float, float], Tuple[float, float]]]:
        """Return (box, camera_ground_point, birdseye_point) for every box whose foot point projects
        onto (or just around) the calibrated ground plane."""
        results = []
        target_w = self.calib.config.target_width_px
        target_h = self.calib.config.target_height_px
        for box in boxes:
            cam_pt = box.ground_contact_point
            try:
                be_pt = self.calib.project_camera_to_birdseye(cam_pt)
            except Exception as exc:  # noqa: BLE001 - a point that cannot be projected is skipped, not invented
                logger.debug("Failed to project point %s: %s", cam_pt, exc)
                continue
            if not clip_to_birdseye_bounds or (-50 <= be_pt[0] <= target_w + 50 and -50 <= be_pt[1] <= target_h + 50):
                results.append((box, cam_pt, be_pt))
        return results
