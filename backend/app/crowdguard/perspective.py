"""Bird's-Eye View Generator for CrowdGuard VCIE.

Generates top-down perspective transformations of video frames, draws metric grids,
renders zone polygons, and overlays camera calibration references.

Note: This produces a 2D projective transformation of the ground plane via planar homography.
It does NOT perform full 3D reconstruction and does not reconstruct objects hidden by occlusion.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import cv2
import numpy as np

from .calibration import CameraCalibrationEngine
from .schemas import ZoneDefinition

logger = logging.getLogger(__name__)


class BirdEyeViewGenerator:
    """Generates transformed top-down images and renders visual overlays."""

    def __init__(self, calibration: CameraCalibrationEngine):
        self.calib = calibration

    def warp_frame(
        self,
        frame: np.ndarray,
        target_resolution: Optional[Tuple[int, int]] = None,
        interpolation: int = cv2.INTER_LINEAR,
    ) -> np.ndarray:
        """Warps a conventional camera image into the bird's-eye ground plane perspective.
        
        Args:
            frame: Input camera frame as BGR uint8 numpy array.
            target_resolution: Optional (width, height). Defaults to calibration config.
            interpolation: OpenCV interpolation mode.
            
        Returns:
            Bird's-eye transformed BGR frame.
        """
        if not self.calib.is_valid or self.calib.H is None:
            raise ValueError("Cannot warp frame: Calibration is invalid.")

        width = target_resolution[0] if target_resolution else self.calib.config.target_width_px
        height = target_resolution[1] if target_resolution else self.calib.config.target_height_px

        warped = cv2.warpPerspective(
            frame,
            self.calib.H,
            (width, height),
            flags=interpolation,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(18, 18, 22),  # sleek dark background
        )
        return warped

    def draw_metric_grid(
        self,
        birdseye_image: np.ndarray,
        grid_step_meters: float = 2.0,
        grid_color: Tuple[int, int, int] = (60, 60, 75),
        line_thickness: int = 1,
        draw_labels: bool = True,
    ) -> np.ndarray:
        """Overlays a physical metric grid onto the bird's-eye canvas.
        
        Uses calibrated meters_per_pixel to draw real-world spaced grid lines.
        """
        out = birdseye_image.copy()
        h, w = out.shape[:2]
        res = self.calib.result

        if not res or not res.meters_per_pixel_x or not res.meters_per_pixel_y:
            # Fallback to pixel-based grid if metric calibration unavailable
            step_px = 50
            for x in range(0, w, step_px):
                cv2.line(out, (x, 0), (x, h), grid_color, line_thickness, cv2.LINE_AA)
            for y in range(0, h, step_px):
                cv2.line(out, (0, y), (w, y), grid_color, line_thickness, cv2.LINE_AA)
            return out

        m_px_x = res.meters_per_pixel_x
        m_px_y = res.meters_per_pixel_y
        step_px_x = int(round(grid_step_meters / m_px_x))
        step_px_y = int(round(grid_step_meters / m_px_y))

        if step_px_x <= 5 or step_px_y <= 5:
            return out

        # Draw vertical lines
        meter_x = 0.0
        for x in range(0, w, step_px_x):
            cv2.line(out, (x, 0), (x, h), grid_color, line_thickness, cv2.LINE_AA)
            if draw_labels and x + 40 < w:
                label = f"{meter_x:.0f}m"
                cv2.putText(out, label, (x + 4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 140), 1, cv2.LINE_AA)
            meter_x += grid_step_meters

        # Draw horizontal lines
        meter_y = 0.0
        for y in range(0, h, step_px_y):
            cv2.line(out, (0, y), (w, y), grid_color, line_thickness, cv2.LINE_AA)
            if draw_labels and y + 20 < h:
                label = f"{meter_y:.0f}m"
                cv2.putText(out, label, (6, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 140), 1, cv2.LINE_AA)
            meter_y += grid_step_meters

        return out

    def draw_calibration_overlay_on_camera(
        self,
        camera_frame: np.ndarray,
        color: Tuple[int, int, int] = (0, 215, 255),  # gold/amber
        thickness: int = 2,
    ) -> np.ndarray:
        """Renders the calibrated 4-point ground quadrilateral and corner pins on the camera image."""
        out = camera_frame.copy()
        pts = self.calib.config.source_points.to_list()
        pts_np = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))

        # Semi-transparent ground polygon fill
        overlay = out.copy()
        cv2.fillPoly(overlay, [pts_np], color=(0, 120, 160))
        cv2.addWeighted(overlay, 0.25, out, 0.75, 0, out)

        # Polygon outline
        cv2.polylines(out, [pts_np], isClosed=True, color=color, thickness=thickness, lineType=cv2.LINE_AA)

        labels = ["TL", "TR", "BR", "BL"]
        for i, (x, y) in enumerate(pts):
            ix, iy = int(round(x)), int(round(y))
            cv2.circle(out, (ix, iy), 6, (0, 255, 0), -1, cv2.LINE_AA)
            cv2.circle(out, (ix, iy), 8, color, 1, cv2.LINE_AA)
            cv2.putText(out, f"{labels[i]} ({ix},{iy})", (ix + 8, iy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        return out

    def draw_zones(
        self,
        birdseye_image: np.ndarray,
        zones: List[ZoneDefinition],
        fill_alpha: float = 0.15,
    ) -> np.ndarray:
        """Renders designated venue zones (polygons) on bird's-eye canvas."""
        out = birdseye_image.copy()
        colors = [
            (240, 140, 40),  # blue/cyan
            (40, 200, 100),  # green
            (60, 140, 255),  # amber
            (200, 60, 220),  # purple
            (60, 60, 240),   # red
        ]

        overlay = out.copy()
        for idx, zone in enumerate(zones):
            c = colors[idx % len(colors)]
            pts = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(overlay, [pts], color=c)
            cv2.polylines(out, [pts], isClosed=True, color=c, thickness=2, lineType=cv2.LINE_AA)

            # Zone label at polygon centroid
            moments = cv2.moments(pts)
            if moments["m00"] > 0:
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])
                cv2.putText(out, zone.name, (cx - 40, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.addWeighted(overlay, fill_alpha, out, 1.0 - fill_alpha, 0, out)
        return out
