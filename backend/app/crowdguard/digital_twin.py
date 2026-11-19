"""Virtual Venue Digital Twin Engine for CrowdGuard VCIE.

Renders high-fidelity top-down 2D digital twin models of monitored venues,
including architectural boundaries, walkable corridors, obstacles, ingress/egress portals,
and live crowd telemetry overlays. Supports both calibrated camera maps and schematic maps.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from pydantic import BaseModel, Field

from .schemas import (
    DensityRiskLevel,
    MovementVector,
    TrackedPerson,
    ZoneDefinition,
    ZoneMetric,
)

logger = logging.getLogger(__name__)


class Portal(BaseModel):
    """An entrance or exit portal."""
    id: str
    name: str
    portal_type: str = Field(..., description="entrance | exit | emergency_egress")
    line: Tuple[Tuple[float, float], Tuple[float, float]] = Field(..., description="Start and end point in birdseye px")
    width_meters: float = 3.0


class Obstacle(BaseModel):
    """An architectural obstacle (column, wall, kiosk, security barrier)."""
    id: str
    name: str
    shape: str = Field("rect", description="rect | circle | polygon")
    polygon: List[Tuple[float, float]]
    is_walkable: bool = False


class VenueDigitalTwinModel(BaseModel):
    """Digital twin configuration and architectural definition of a monitored venue."""
    venue_id: str
    venue_name: str
    canvas_width_px: int = 800
    canvas_height_px: int = 600
    world_width_meters: float = 24.0
    world_height_meters: float = 18.0
    walkable_polygon: List[Tuple[float, float]]
    zones: List[ZoneDefinition]
    portals: List[Portal] = Field(default_factory=list)
    obstacles: List[Obstacle] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VenueDigitalTwin:
    """Renderer and spatial query manager for the virtual venue digital twin."""

    def __init__(self, model: Optional[VenueDigitalTwinModel] = None):
        self.model = model or self.get_default_plaza_preset()

    @classmethod
    def get_default_plaza_preset(cls) -> VenueDigitalTwinModel:
        """Standard plaza and concourse venue preset (800x600)."""
        w, h = 800.0, 600.0
        # Walkable area with margin
        walkable = [
            (40.0, 40.0),
            (w - 40.0, 40.0),
            (w - 40.0, h - 40.0),
            (40.0, h - 40.0),
        ]

        # 4 distinct functional zones
        zones = [
            ZoneDefinition(
                id="zone-a",
                name="North Ingress Gate",
                polygon=[(60.0, 50.0), (380.0, 50.0), (380.0, 240.0), (60.0, 240.0)],
                capacity=40,
                area_sq_meters=48.0,
            ),
            ZoneDefinition(
                id="zone-b",
                name="Central Gathering Plaza",
                polygon=[(400.0, 50.0), (740.0, 50.0), (740.0, 320.0), (400.0, 320.0)],
                capacity=85,
                area_sq_meters=96.0,
            ),
            ZoneDefinition(
                id="zone-c",
                name="Main Concourse",
                polygon=[(60.0, 260.0), (380.0, 260.0), (380.0, 550.0), (60.0, 550.0)],
                capacity=60,
                area_sq_meters=68.0,
            ),
            ZoneDefinition(
                id="zone-d",
                name="South Egress Corridor",
                polygon=[(400.0, 340.0), (740.0, 340.0), (740.0, 550.0), (400.0, 550.0)],
                capacity=45,
                area_sq_meters=52.0,
            ),
        ]

        portals = [
            Portal(id="p-in-1", name="Main North Gate A", portal_type="entrance", line=((120.0, 40.0), (280.0, 40.0))),
            Portal(id="p-out-1", name="South Exit 1", portal_type="exit", line=((500.0, 560.0), (660.0, 560.0))),
            Portal(id="p-em-1", name="Emergency Egress E1", portal_type="emergency_egress", line=((760.0, 160.0), (760.0, 260.0))),
        ]

        obstacles = [
            Obstacle(
                id="obs-col-1",
                name="Central Pillar 1",
                shape="rect",
                polygon=[(382.0, 270.0), (398.0, 270.0), (398.0, 310.0), (382.0, 310.0)],
            ),
            Obstacle(
                id="obs-kiosk",
                name="Information Kiosk",
                shape="rect",
                polygon=[(520.0, 160.0), (580.0, 160.0), (580.0, 200.0), (520.0, 200.0)],
            ),
        ]

        return VenueDigitalTwinModel(
            venue_id="venue-plaza-01",
            venue_name="Demonstration Plaza & Main Concourse",
            canvas_width_px=800,
            canvas_height_px=600,
            world_width_meters=24.0,
            world_height_meters=18.0,
            walkable_polygon=walkable,
            zones=zones,
            portals=portals,
            obstacles=obstacles,
        )

    def render_base_schematic(self) -> np.ndarray:
        """Renders an architectural top-down schematic map of the venue."""
        w = self.model.canvas_width_px
        h = self.model.canvas_height_px
        # Modern blueprint dark slate canvas
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[:] = (20, 22, 28)

        # 1. Draw walkable floor
        walk_pts = np.array(self.model.walkable_polygon, dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(canvas, [walk_pts], (28, 32, 40))
        cv2.polylines(canvas, [walk_pts], isClosed=True, color=(55, 62, 75), thickness=2, lineType=cv2.LINE_AA)

        # Subtle floor grid
        grid_step = 40
        for x in range(0, w, grid_step):
            cv2.line(canvas, (x, 0), (x, h), (26, 30, 38), 1)
        for y in range(0, h, grid_step):
            cv2.line(canvas, (0, y), (w, y), (26, 30, 38), 1)

        # 2. Draw Zones
        for z in self.model.zones:
            z_pts = np.array(z.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(canvas, [z_pts], isClosed=True, color=(70, 85, 110), thickness=1, lineType=cv2.LINE_AA)
            # Label
            m = cv2.moments(z_pts)
            if m["m00"] > 0:
                cx = int(m["m10"] / m["m00"])
                cy = int(m["m01"] / m["m00"])
                cv2.putText(canvas, z.name, (cx - 50, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 140, 170), 1, cv2.LINE_AA)
                cv2.putText(canvas, f"Cap: {z.capacity} ({z.area_sq_meters:.0f} m2)", (cx - 40, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (85, 100, 125), 1, cv2.LINE_AA)

        # 3. Draw Obstacles (Pillars, walls, kiosks)
        for obs in self.model.obstacles:
            o_pts = np.array(obs.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(canvas, [o_pts], (45, 48, 56))
            cv2.polylines(canvas, [o_pts], isClosed=True, color=(180, 80, 80), thickness=1, lineType=cv2.LINE_AA)
            cv2.putText(canvas, obs.name, (int(obs.polygon[0][0]), int(obs.polygon[0][1]) - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (160, 100, 100), 1, cv2.LINE_AA)

        # 4. Draw Portals (Entrances, Exits)
        for p in self.model.portals:
            p1 = (int(p.line[0][0]), int(p.line[0][1]))
            p2 = (int(p.line[1][0]), int(p.line[1][1]))
            if p.portal_type == "entrance":
                color = (60, 220, 100)  # green
            elif p.portal_type == "exit":
                color = (240, 160, 40)  # blue/cyan
            else:
                color = (60, 60, 250)   # red (emergency)

            cv2.line(canvas, p1, p2, color, 4, cv2.LINE_AA)
            mid = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
            cv2.putText(canvas, p.name, (mid[0] - 30, mid[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)

        return canvas

    def render_digital_twin_with_telemetry(
        self,
        tracks: List[TrackedPerson],
        zone_metrics: List[ZoneMetric],
        movement_vectors: List[MovementVector],
        heatmap_overlay: Optional[np.ndarray] = None,
        is_schematic: bool = True,
        base_camera_warped: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Renders comprehensive digital twin view combining venue floor, live people, and analytics."""
        if not is_schematic and base_camera_warped is not None:
            canvas = base_camera_warped.copy()
        else:
            canvas = self.render_base_schematic()

        # Blend heatmap if provided
        if heatmap_overlay is not None:
            cv2.addWeighted(heatmap_overlay, 0.65, canvas, 0.35, 0, canvas)

        # Draw live people nodes
        for trk in tracks:
            bx, by = trk.birdseye_point
            ix, iy = int(round(bx)), int(round(by))
            if 0 <= ix < canvas.shape[1] and 0 <= iy < canvas.shape[0]:
                # Pin with outer glow
                cv2.circle(canvas, (ix, iy), 5, (0, 220, 255), -1, cv2.LINE_AA)
                cv2.circle(canvas, (ix, iy), 7, (255, 255, 255), 1, cv2.LINE_AA)

        # Draw movement vectors
        for v in movement_vectors:
            p1 = (int(round(v.start_x)), int(round(v.start_y)))
            p2 = (int(round(v.end_x)), int(round(v.end_y)))
            if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) >= 4:
                c = (40, 40, 240) if v.risk_indicator == "stagnant" else (60, 220, 100)
                cv2.arrowedLine(canvas, p1, p2, c, 2, tipLength=0.35, line_type=cv2.LINE_AA)

        # Header watermark
        title = f"DIGITAL TWIN: {self.model.venue_name} [{'SCHEMATIC' if is_schematic else 'CALIBRATED CAMERA'}]"
        cv2.putText(canvas, title, (16, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 220), 1, cv2.LINE_AA)

        return canvas
