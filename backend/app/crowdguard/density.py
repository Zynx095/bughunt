"""Virtual Crowd Density Engine for CrowdGuard VCIE.

Computes continuous Gaussian Kernel Density Estimation (KDE) over bird's-eye coordinates,
converts pixel density into physical persons per square metre (when spatial calibration is active),
evaluates zone populations, and renders multi-mode heatmaps.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import cv2
import numpy as np

from .calibration import CameraCalibrationEngine
from .schemas import (
    DensityRiskLevel,
    HeatmapMode,
    TrackedPerson,
    ZoneDefinition,
    ZoneMetric,
)

logger = logging.getLogger(__name__)


class VirtualCrowdDensityEngine:
    """Computes spatial crowd density distributions and renders multi-mode heatmaps."""

    def __init__(
        self,
        calibration: CameraCalibrationEngine,
        bandwidth_sigma: float = 28.0,
        density_threshold_high: float = 1.5,     # persons/m^2
        density_threshold_critical: float = 3.0, # persons/m^2
    ):
        self.calib = calibration
        self.bandwidth_sigma = bandwidth_sigma
        self.density_threshold_high = density_threshold_high
        self.density_threshold_critical = density_threshold_critical

    def compute_density_grid(
        self,
        tracks: List[TrackedPerson],
        grid_width: Optional[int] = None,
        grid_height: Optional[int] = None,
        bandwidth_sigma: Optional[float] = None,
        weight_by_inversed_speed: bool = False,
    ) -> np.ndarray:
        """Computes continuous Gaussian Kernel Density Estimation (KDE) grid.
        
        If metric calibration is available, the grid values represent physical
        density in units of persons per square metre (persons/m^2).
        Otherwise, values represent relative local person concentrations.
        
        Args:
            tracks: List of active tracked people with birdseye_point coordinates.
            grid_width: Output grid width in pixels (defaults to calibration width).
            grid_height: Output grid height in pixels (defaults to calibration height).
            bandwidth_sigma: Gaussian kernel radius in pixels.
            weight_by_inversed_speed: If True, stagnant/slow individuals contribute higher weight.
            
        Returns:
            2D float32 numpy array representing density values.
        """
        w = grid_width or self.calib.config.target_width_px
        h = grid_height or self.calib.config.target_height_px
        sigma = bandwidth_sigma or self.bandwidth_sigma

        # Accumulator grid
        accumulator = np.zeros((h, w), dtype=np.float32)

        if not tracks:
            return accumulator

        # Deposit discrete impulses
        for trk in tracks:
            bx, by = trk.birdseye_point
            ix, iy = int(round(bx)), int(round(by))
            if 0 <= ix < w and 0 <= iy < h:
                weight = 1.0
                if weight_by_inversed_speed:
                    # Slow moving or stationary people have higher accumulation weight
                    weight = 1.0 + max(0.0, 1.5 - min(1.5, trk.speed_mps))
                accumulator[iy, ix] += weight

        # Apply continuous Gaussian kernel via separable 2D convolution
        # Kernel size roughly 6 * sigma to capture 99.7% of Gaussian mass
        ksize = int(math_round_odd(max(7, sigma * 4.0)))
        kde = cv2.GaussianBlur(accumulator, (ksize, ksize), sigmaX=sigma, sigmaY=sigma)

        # Normalization to physical units:
        # A 2D Gaussian kernel of standard deviation sigma has continuous integral:
        # \iint G(x, y; \sigma) dx dy = 1
        # When discretized into pixels with dx = dy = 1, sum over all pixels of one impulse = 1.0.
        # To convert to persons / m^2:
        # area of one pixel = (meters_per_pixel_x * meters_per_pixel_y) m^2.
        # Local density at pixel = (fraction of person in pixel) / (area of pixel in m^2).
        res = self.calib.result
        if res and res.meters_per_pixel_x and res.meters_per_pixel_y:
            pixel_area_m2 = res.meters_per_pixel_x * res.meters_per_pixel_y
            # Physical density in persons / m^2
            density_grid = kde / pixel_area_m2
        else:
            # Fallback relative scaling: arbitrary default scale 1000.0 * kde
            density_grid = kde * 1000.0

        return density_grid.astype(np.float32)

    def evaluate_zones(
        self,
        tracks: List[TrackedPerson],
        zones: List[ZoneDefinition],
    ) -> List[ZoneMetric]:
        """Calculates real-time occupancy, density, speed, and risk for predefined venue zones."""
        metrics: List[ZoneMetric] = []
        res = self.calib.result
        m_x = (res.meters_per_pixel_x or 0.03) if res else 0.03
        m_y = (res.meters_per_pixel_y or 0.03) if res else 0.03

        for zone in zones:
            pts = np.array(zone.polygon, dtype=np.float32)
            pts_int = pts.astype(np.int32).reshape((-1, 1, 2))

            # Point-in-polygon containment test for each track
            in_zone_tracks: List[TrackedPerson] = []
            for trk in tracks:
                pt = (float(trk.birdseye_point[0]), float(trk.birdseye_point[1]))
                # cv2.pointPolygonTest returns > 0 for inside, 0 on edge, < 0 outside
                if cv2.pointPolygonTest(pts_int, pt, measureDist=False) >= 0:
                    in_zone_tracks.append(trk)
                    trk.zone_id = zone.id

            pop = len(in_zone_tracks)
            capacity = zone.capacity
            occupancy_pct = (pop / capacity * 100.0) if capacity > 0 else 0.0

            # Compute physical area if not explicitly specified
            if zone.area_sq_meters and zone.area_sq_meters > 0:
                area_m2 = zone.area_sq_meters
            else:
                pixel_area = cv2.contourArea(pts_int)
                area_m2 = max(1.0, pixel_area * m_x * m_y)

            density = pop / area_m2
            avg_speed = (sum(t.speed_mps for t in in_zone_tracks) / pop) if pop > 0 else 0.0

            # Determine risk level
            if density >= zone.risk_threshold_critical or occupancy_pct >= 100.0:
                risk = DensityRiskLevel.CRITICAL
                status_msg = f"CRITICAL: Overcrowding in {zone.name} ({pop}/{capacity} pers, {density:.1f} p/m²)"
            elif density >= zone.risk_threshold_high or occupancy_pct >= 75.0:
                risk = DensityRiskLevel.HIGH
                status_msg = f"HIGH DENSITY: Congestion building in {zone.name} ({density:.1f} p/m²)"
            elif density >= 0.5 or occupancy_pct >= 40.0:
                risk = DensityRiskLevel.MODERATE
                status_msg = f"MODERATE: Normal active movement in {zone.name}"
            else:
                risk = DensityRiskLevel.LOW
                status_msg = f"NORMAL: Low density in {zone.name}"

            metrics.append(
                ZoneMetric(
                    zone_id=zone.id,
                    zone_name=zone.name,
                    population=pop,
                    capacity=capacity,
                    occupancy_pct=round(occupancy_pct, 1),
                    area_sq_meters=round(area_m2, 1),
                    density_per_sq_meter=round(density, 2),
                    avg_speed_mps=round(avg_speed, 2),
                    risk_level=risk,
                    status_message=status_msg,
                )
            )

        return metrics

    def render_heatmap(
        self,
        base_image: np.ndarray,
        tracks: List[TrackedPerson],
        zones: Optional[List[ZoneDefinition]] = None,
        mode: HeatmapMode = HeatmapMode.GAUSSIAN,
        alpha: float = 0.65,
        bandwidth_sigma: Optional[float] = None,
    ) -> np.ndarray:
        """Renders the selected heatmap visualization onto base_image.
        
        Modes:
            - GAUSSIAN: Continuous smooth Gaussian KDE colormap
            - POINT: Discrete blurred person nodes with glow
            - ZONE: Choropleth zones colored by density
            - MOVEMENT: Velocity-weighted density highlighting stationary congestion
        """
        h, w = base_image.shape[:2]

        if mode == HeatmapMode.ZONE and zones:
            return self._render_zone_heatmap(base_image, tracks, zones, alpha)

        # 1. Compute density grid
        weight_movement = (mode == HeatmapMode.MOVEMENT)
        sigma = 16.0 if mode == HeatmapMode.POINT else (bandwidth_sigma or self.bandwidth_sigma)
        density_grid = self.compute_density_grid(
            tracks=tracks,
            grid_width=w,
            grid_height=h,
            bandwidth_sigma=sigma,
            weight_by_inversed_speed=weight_movement,
        )

        # 2. Normalize density to [0, 255] uint8 for colormapping
        # 4.0 persons/m^2 corresponds to saturation
        max_calib_density = max(1.5, self.density_threshold_critical * 1.3)
        normalized = np.clip(density_grid / max_calib_density * 255.0, 0, 255).astype(np.uint8)

        # 3. Apply color map (JET or TURBO provides familiar blue-green-yellow-red crowd gradient)
        colored_heat = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)

        # 4. Create alpha mask: zero density regions stay transparent
        # Threshold out noise below ~0.05 persons/m^2
        noise_cutoff = int(0.05 / max_calib_density * 255)
        mask = cv2.threshold(normalized, noise_cutoff, 255, cv2.THRESH_BINARY)[1]
        mask_f = (mask.astype(np.float32) / 255.0) * alpha

        # 5. Alpha blend with base image
        out = base_image.copy().astype(np.float32)
        heat_f = colored_heat.astype(np.float32)

        for c in range(3):
            out[:, :, c] = out[:, :, c] * (1.0 - mask_f) + heat_f[:, :, c] * mask_f

        # If in POINT mode, draw sharp center pins for exact locations
        if mode == HeatmapMode.POINT:
            out_uint = np.clip(out, 0, 255).astype(np.uint8)
            for trk in tracks:
                bx, by = trk.birdseye_point
                ix, iy = int(round(bx)), int(round(by))
                if 0 <= ix < w and 0 <= iy < h:
                    cv2.circle(out_uint, (ix, iy), 3, (255, 255, 255), -1, cv2.LINE_AA)
            return out_uint

        return np.clip(out, 0, 255).astype(np.uint8)

    def _render_zone_heatmap(
        self,
        base_image: np.ndarray,
        tracks: List[TrackedPerson],
        zones: List[ZoneDefinition],
        alpha: float,
    ) -> np.ndarray:
        """Renders zone choropleth based on evaluated density level."""
        metrics = self.evaluate_zones(tracks, zones)
        out = base_image.copy()
        overlay = out.copy()

        risk_colors = {
            DensityRiskLevel.LOW: (160, 200, 40),      # calm greenish
            DensityRiskLevel.MODERATE: (50, 180, 240), # yellow/amber
            DensityRiskLevel.HIGH: (30, 90, 240),      # orange
            DensityRiskLevel.CRITICAL: (40, 40, 240),  # vibrant red
        }

        for m in metrics:
            zone = next((z for z in zones if z.id == m.zone_id), None)
            if not zone:
                continue
            color = risk_colors.get(m.risk_level, (100, 100, 100))
            pts = np.array(zone.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(overlay, [pts], color=color)
            cv2.polylines(out, [pts], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)

        cv2.addWeighted(overlay, alpha, out, 1.0 - alpha, 0, out)
        return out


def math_round_odd(val: float) -> int:
    """Rounds to the nearest odd integer for convolution kernel sizes."""
    i = int(round(val))
    return i if i % 2 == 1 else i + 1
