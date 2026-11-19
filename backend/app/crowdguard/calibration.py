"""Camera Calibration Engine for CrowdGuard VCIE.

Computes 3x3 planar homography transformation matrix H between camera image plane
and top-down bird's-eye ground plane using 4-point projective calibration.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import numpy as np
import cv2

from .schemas import CalibrationConfig, CalibrationPoint, CalibrationQuad, CalibrationResult

logger = logging.getLogger(__name__)


def order_points_clockwise(pts: np.ndarray) -> np.ndarray:
    """Orders 4 points as [Top-Left, Top-Right, Bottom-Right, Bottom-Left].
    
    Uses sum (x+y) and diff (y-x) properties:
    - TL has minimum (x + y)
    - BR has maximum (x + y)
    - TR has minimum (y - x) [maximum (x - y)]
    - BL has maximum (y - x) [minimum (x - y)]
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # Top-Left
    rect[2] = pts[np.argmax(s)]  # Bottom-Right

    diff = np.diff(pts, axis=1)  # y - x
    rect[1] = pts[np.argmin(diff)]  # Top-Right
    rect[3] = pts[np.argmax(diff)]  # Bottom-Left
    return rect


def is_convex_quad(pts: np.ndarray) -> bool:
    """Verifies that 4 ordered vertices form a strictly convex quadrilateral.
    
    All consecutive cross-products (z-component) must share the same sign.
    """
    if len(pts) != 4:
        return False
    cross_signs = []
    for i in range(4):
        p1 = pts[i]
        p2 = pts[(i + 1) % 4]
        p3 = pts[(i + 2) % 4]
        v1 = p2 - p1
        v2 = p3 - p2
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        if abs(cross) < 1e-5:
            # Collinear edge
            return False
        cross_signs.append(cross > 0)
    return len(set(cross_signs)) == 1


class CameraCalibrationEngine:
    """Engine responsible for computing, validating, and managing ground-plane homographies."""

    def __init__(self, config: Optional[CalibrationConfig] = None):
        self.config = config or self.get_default_calibration()
        self._result: Optional[CalibrationResult] = None
        self._H: Optional[np.ndarray] = None
        self._H_inv: Optional[np.ndarray] = None
        self.calibrate(self.config)

    @classmethod
    def get_default_calibration(cls) -> CalibrationConfig:
        """Returns standard demonstration perspective calibration (e.g. 1280x720 camera)."""
        quad = CalibrationQuad(
            top_left=CalibrationPoint(x=430.0, y=280.0),
            top_right=CalibrationPoint(x=850.0, y=280.0),
            bottom_right=CalibrationPoint(x=1150.0, y=680.0),
            bottom_left=CalibrationPoint(x=130.0, y=680.0),
        )
        return CalibrationConfig(
            source_points=quad,
            target_width_px=800,
            target_height_px=600,
            ground_width_meters=24.0,
            ground_height_meters=18.0,
            venue_name="Demonstration Plaza & Main Concourse",
        )

    def calibrate(self, config: CalibrationConfig) -> CalibrationResult:
        """Calculates and validates homography matrix from source points to top-down canvas."""
        self.config = config
        warnings: List[str] = []

        raw_pts = np.array(config.source_points.to_list(), dtype=np.float32)

        # Validate quad non-degeneracy
        if not is_convex_quad(raw_pts):
            # Try auto-ordering points in clockwise order
            ordered = order_points_clockwise(raw_pts)
            if not is_convex_quad(ordered):
                err_msg = "Degenerate calibration: Reference points do not form a strictly convex 4-point ground quadrilateral (collinear or self-intersecting points)."
                logger.warning(err_msg)
                self._result = CalibrationResult(
                    valid=False,
                    target_width_px=config.target_width_px,
                    target_height_px=config.target_height_px,
                    message=err_msg,
                    warnings=["Points are collinear or self-intersecting"],
                )
                self._H = None
                self._H_inv = None
                return self._result
            warnings.append("Reference points were re-ordered to form a convex clockwise quadrilateral [TL, TR, BR, BL].")
            src = ordered
        else:
            src = raw_pts

        w = float(config.target_width_px)
        h = float(config.target_height_px)

        # Destination points in top-down bird's-eye canvas:
        # TL = (0, 0), TR = (w, 0), BR = (w, h), BL = (0, h)
        dst = np.array([
            [0.0, 0.0],
            [w, 0.0],
            [w, h],
            [0.0, h],
        ], dtype=np.float32)

        # Calculate perspective transformation matrix H (3x3)
        try:
            H = cv2.getPerspectiveTransform(src, dst)
        except Exception as e:
            err_msg = f"OpenCV getPerspectiveTransform failed: {str(e)}"
            logger.error(err_msg)
            self._result = CalibrationResult(
                valid=False,
                target_width_px=config.target_width_px,
                target_height_px=config.target_height_px,
                message=err_msg,
            )
            self._H = None
            self._H_inv = None
            return self._result

        # Check conditioning and invertibility
        det = np.linalg.det(H)
        if abs(det) < 1e-12:
            err_msg = "Singular homography matrix computed (determinant near 0)."
            self._result = CalibrationResult(
                valid=False,
                target_width_px=config.target_width_px,
                target_height_px=config.target_height_px,
                message=err_msg,
            )
            self._H = None
            self._H_inv = None
            return self._result

        cond = np.linalg.cond(H)
        if cond > 1e6:
            warnings.append(f"Homography has high condition number ({cond:.1e}), which may cause numerical instability at extreme perspective angles.")

        try:
            H_inv = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            err_msg = "Matrix inversion failed for calculated homography."
            self._result = CalibrationResult(
                valid=False,
                target_width_px=config.target_width_px,
                target_height_px=config.target_height_px,
                message=err_msg,
            )
            self._H = None
            self._H_inv = None
            return self._result

        # Physical metric calibration
        m_per_px_x = (config.ground_width_meters / w) if config.ground_width_meters else None
        m_per_px_y = (config.ground_height_meters / h) if config.ground_height_meters else None
        area_m2 = (config.ground_width_meters * config.ground_height_meters) if (config.ground_width_meters and config.ground_height_meters) else None

        self._H = H
        self._H_inv = H_inv

        self._result = CalibrationResult(
            valid=True,
            homography_matrix=H.tolist(),
            inverse_homography_matrix=H_inv.tolist(),
            target_width_px=config.target_width_px,
            target_height_px=config.target_height_px,
            meters_per_pixel_x=m_per_px_x,
            meters_per_pixel_y=m_per_px_y,
            ground_area_sq_meters=area_m2,
            condition_number=float(cond),
            message="Calibration successful. Homography established.",
            warnings=warnings,
        )
        return self._result

    @property
    def is_valid(self) -> bool:
        return self._result is not None and self._result.valid and self._H is not None

    @property
    def H(self) -> Optional[np.ndarray]:
        return self._H

    @property
    def H_inv(self) -> Optional[np.ndarray]:
        return self._H_inv

    @property
    def result(self) -> Optional[CalibrationResult]:
        return self._result

    def project_camera_to_birdseye(self, point: Tuple[float, float]) -> Tuple[float, float]:
        """Projects a point from camera pixel coordinates (x, y) to bird's-eye canvas coordinates (u, v).
        
        Using homogeneous coordinates:
        [u', v', w']^T = H * [x, y, 1]^T
        u = u' / w', v = v' / w'
        """
        if self._H is None:
            raise ValueError("Calibration has not been initialized or is invalid.")
        pt = np.array([point[0], point[1], 1.0], dtype=np.float64)
        res = self._H @ pt
        w = res[2]
        if abs(w) < 1e-9:
            w = 1e-9 if w >= 0 else -1e-9
        return (float(res[0] / w), float(res[1] / w))

    def project_birdseye_to_camera(self, point: Tuple[float, float]) -> Tuple[float, float]:
        """Projects a point from bird's-eye coordinates (u, v) back to camera image coordinates (x, y)."""
        if self._H_inv is None:
            raise ValueError("Calibration has not been initialized or is invalid.")
        pt = np.array([point[0], point[1], 1.0], dtype=np.float64)
        res = self._H_inv @ pt
        w = res[2]
        if abs(w) < 1e-9:
            w = 1e-9 if w >= 0 else -1e-9
        return (float(res[0] / w), float(res[1] / w))

    def to_world_meters(self, birdseye_pt: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """Converts bird's-eye pixel coordinates to physical (meters_x, meters_y) relative to top-left origin."""
        if not self._result or not self._result.meters_per_pixel_x or not self._result.meters_per_pixel_y:
            return None
        return (
            birdseye_pt[0] * self._result.meters_per_pixel_x,
            birdseye_pt[1] * self._result.meters_per_pixel_y,
        )
