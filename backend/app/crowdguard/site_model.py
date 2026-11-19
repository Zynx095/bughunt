"""The monitored site: the ground plane one camera observes, in metres.

Coordinates: x grows to the right and y grows "down" the top-down map (away from the camera's far edge
towards its near edge), origin at the top-left corner of the site. The camera is linked to this
plane by a four-point homography (calibration.py). The site is divided into square cells for the
occupancy / free-space analysis and for grid route planning.

Geometry that operators configure: walkable boundary, obstacles, zones (with capacity, optionally
restricted), and portals (entrances, exits, emergency exits, each available or not).
"""
from __future__ import annotations

import math
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from .calibration import CameraCalibrationEngine
from .schemas import CalibrationConfig, CalibrationPoint, CalibrationQuad
from .zone_manager import point_in_polygon, polygon_area, polygon_centroid

CANVAS_W, CANVAS_H = 800, 600  # bird's-eye canvas used by the calibration engine (fixed resolution)
Pt = tuple[float, float]


class Portal(BaseModel):
    id: str = Field(..., max_length=40)
    name: str = Field(..., max_length=80)
    kind: Literal["entrance", "exit", "emergency_exit"]
    a: Pt
    b: Pt
    available: bool = True  # operator-reported: False means obstructed / closed by an observed condition

    @property
    def center(self) -> Pt:
        return ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)

    @property
    def width_m(self) -> float:
        return math.dist(self.a, self.b)

    @property
    def capacity_ppm(self) -> float:
        return round(self.width_m * 82.0, 1)  # planning flow, persons per metre width per minute


class SiteZone(BaseModel):
    id: str = Field(..., max_length=40)
    name: str = Field(..., max_length=80)
    polygon: list[Pt] = Field(..., min_length=3, max_length=64)
    capacity: Optional[int] = Field(None, gt=0)
    restricted: bool = False  # restricted zones are never walkable for routing

    @property
    def area_m2(self) -> float:
        return polygon_area(self.polygon)


class Obstacle(BaseModel):
    id: str = Field(..., max_length=40)
    name: str = Field(..., max_length=80)
    polygon: list[Pt] = Field(..., min_length=3, max_length=64)


class SiteModel(BaseModel):
    id: str = "site"
    name: str = "Monitored area"
    width_m: float = Field(24.0, gt=1, le=500)
    height_m: float = Field(18.0, gt=1, le=500)
    cell_m: float = Field(0.75, ge=0.25, le=5)
    walkable: Optional[list[Pt]] = None  # None = the whole site rectangle
    obstacles: list[Obstacle] = Field(default_factory=list)
    zones: list[SiteZone] = Field(default_factory=list)
    portals: list[Portal] = Field(default_factory=list)
    # Thresholds in persons/m² (only interpreted as metric when the calibration is confirmed).
    occupied_density: float = Field(0.5, gt=0)
    congested_density: float = Field(2.0, gt=0)
    kde_sigma_m: float = Field(0.8, gt=0.1, le=5)

    @field_validator("walkable")
    @classmethod
    def _poly(cls, v):
        if v is not None and len(v) < 3:
            raise ValueError("walkable polygon needs at least 3 points")
        return v

    @model_validator(mode="after")
    def _ids(self):
        ids = [x.id for x in (*self.obstacles, *self.zones, *self.portals)]
        if len(ids) != len(set(ids)):
            raise ValueError("obstacle, zone and portal ids must be unique")
        if self.congested_density <= self.occupied_density:
            raise ValueError("congested_density must be greater than occupied_density")
        return self

    @property
    def cols(self) -> int:
        return max(1, math.ceil(self.width_m / self.cell_m))

    @property
    def rows(self) -> int:
        return max(1, math.ceil(self.height_m / self.cell_m))

    def cell_centers(self) -> np.ndarray:
        xs = (np.arange(self.cols) + 0.5) * self.cell_m
        ys = (np.arange(self.rows) + 0.5) * self.cell_m
        gx, gy = np.meshgrid(xs, ys)
        return np.stack([gx, gy], axis=-1)  # rows x cols x 2

    def cell_of(self, p: Pt) -> tuple[int, int]:
        c = int(min(self.cols - 1, max(0, p[0] // self.cell_m)))
        r = int(min(self.rows - 1, max(0, p[1] // self.cell_m)))
        return r, c

    def scaled(self, width_m: float, height_m: float) -> "SiteModel":
        """Rescale all geometry to new site dimensions (used when a calibration measures the real size)."""
        sx, sy = width_m / self.width_m, height_m / self.height_m
        sc = lambda pts: [(round(x * sx, 3), round(y * sy, 3)) for x, y in pts]  # noqa: E731
        return self.model_copy(update={
            "width_m": width_m, "height_m": height_m,
            "walkable": sc(self.walkable) if self.walkable else None,
            "obstacles": [o.model_copy(update={"polygon": sc(o.polygon)}) for o in self.obstacles],
            "zones": [z.model_copy(update={"polygon": sc(z.polygon)}) for z in self.zones],
            "portals": [p.model_copy(update={"a": sc([p.a])[0], "b": sc([p.b])[0]}) for p in self.portals],
        })


class SiteMasks:
    """Per-cell static geometry: blocked (obstacle, outside the walkable area, restricted zone) and zone ids."""

    def __init__(self, site: SiteModel) -> None:
        self.site = site
        centers = site.cell_centers()
        rows, cols = site.rows, site.cols
        self.blocked = np.zeros((rows, cols), dtype=bool)
        self.restricted = np.zeros((rows, cols), dtype=bool)
        self.zone_of = np.full((rows, cols), -1, dtype=np.int32)
        for r in range(rows):
            for c in range(cols):
                p = (float(centers[r, c, 0]), float(centers[r, c, 1]))
                if site.walkable is not None and not point_in_polygon(p, site.walkable):
                    self.blocked[r, c] = True
                if any(point_in_polygon(p, o.polygon) for o in site.obstacles):
                    self.blocked[r, c] = True
                for zi, z in enumerate(site.zones):
                    if point_in_polygon(p, z.polygon):
                        if z.restricted:
                            self.restricted[r, c] = True
                        elif self.zone_of[r, c] < 0:
                            self.zone_of[r, c] = zi
        self.blocked |= self.restricted
        self.centers = centers


class LiveCalibration(BaseModel):
    """Four image points (source-frame pixels, TL, TR, BR, BL) that see the four corners of the site."""

    image_points: list[Pt] = Field(..., min_length=4, max_length=4)
    frame_size: tuple[int, int]
    confirmed: bool = False  # True only when an operator measured the site dimensions on the ground

    @classmethod
    def default_for(cls, frame_w: int, frame_h: int) -> "LiveCalibration":
        """A plausible oblique-camera trapezoid (assumed, not measured)."""
        return cls(image_points=[(0.30 * frame_w, 0.42 * frame_h), (0.70 * frame_w, 0.42 * frame_h),
                                 (0.97 * frame_w, 0.96 * frame_h), (0.03 * frame_w, 0.96 * frame_h)],
                   frame_size=(frame_w, frame_h), confirmed=False)

    def rescaled(self, frame_w: int, frame_h: int) -> "LiveCalibration":
        if (frame_w, frame_h) == tuple(self.frame_size):
            return self
        sx, sy = frame_w / self.frame_size[0], frame_h / self.frame_size[1]
        return self.model_copy(update={"image_points": [(x * sx, y * sy) for x, y in self.image_points],
                                       "frame_size": (frame_w, frame_h)})


class GroundProjector:
    """Camera pixels <-> site metres, built on the shared VCIE calibration engine."""

    def __init__(self, site: SiteModel, cal: LiveCalibration) -> None:
        names = ("top_left", "top_right", "bottom_right", "bottom_left")
        quad = CalibrationQuad(**{n: CalibrationPoint(x=p[0], y=p[1]) for n, p in zip(names, cal.image_points)})
        self.engine = CameraCalibrationEngine(CalibrationConfig(
            source_points=quad, target_width_px=CANVAS_W, target_height_px=CANVAS_H,
            ground_width_meters=site.width_m, ground_height_meters=site.height_m, venue_name=site.name))
        self.site = site
        self.cal = cal
        self.valid = self.engine.is_valid
        self.message = self.engine.result.message if self.engine.result else "invalid"
        self.mx = site.width_m / CANVAS_W
        self.my = site.height_m / CANVAS_H
        # Homogeneous scale can be negative overall; points in front of the camera share the sign of a
        # point known to be on the ground (the calibration quad's centre).
        if self.valid:
            qc = np.mean(np.array(cal.image_points, dtype=float), axis=0)
            self._sign_fwd = float(np.sign((self.engine.H @ np.array([qc[0], qc[1], 1.0]))[2])) or 1.0
            self._sign_inv = float(np.sign((self.engine.H_inv @ np.array([CANVAS_W / 2, CANVAS_H / 2, 1.0]))[2])) or 1.0

    def to_ground(self, px: Pt) -> Optional[Pt]:
        if not self.valid:
            return None
        h = self.engine.H @ np.array([px[0], px[1], 1.0])
        if h[2] * self._sign_fwd <= 1e-9:  # point is above the horizon: no ground intersection
            return None
        return (float(h[0] / h[2] * self.mx), float(h[1] / h[2] * self.my))

    def to_image(self, g: Pt) -> Optional[Pt]:
        if not self.valid:
            return None
        h = self.engine.H_inv @ np.array([g[0] / self.mx, g[1] / self.my, 1.0])
        if h[2] * self._sign_inv <= 1e-9:
            return None
        return (float(h[0] / h[2]), float(h[1] / h[2]))

    def visible_mask(self, centers: np.ndarray) -> np.ndarray:
        """Cells whose centre projects inside the camera frame (in front of the camera)."""
        rows, cols = centers.shape[:2]
        pts = np.concatenate([centers.reshape(-1, 2) / [self.mx, self.my], np.ones((rows * cols, 1))], axis=1)
        h = (self.engine.H_inv @ pts.T).T
        w = h[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            x, y = h[:, 0] / w, h[:, 1] / w
        fw, fh = self.cal.frame_size
        vis = (w * self._sign_inv > 1e-9) & (x >= 0) & (x < fw) & (y >= 0) & (y < fh)
        return vis.reshape(rows, cols)

    def footprint_uncertainty(self, foot: Pt, box_h: float) -> float:
        """Metres of ground error for a ±6 % box-height error in the foot point (perspective-aware)."""
        a = self.to_ground(foot)
        b = self.to_ground((foot[0], foot[1] - 0.06 * box_h))
        if a is None or b is None:
            return 2.0
        return round(min(5.0, max(0.15, math.dist(a, b))), 2)


def default_site() -> SiteModel:
    """The VCIE demonstration plaza (same geometry as the digital-twin preset), expressed in metres."""
    from .digital_twin import VenueDigitalTwin  # noqa: PLC0415

    m = VenueDigitalTwin.get_default_plaza_preset()
    sx, sy = m.world_width_meters / m.canvas_width_px, m.world_height_meters / m.canvas_height_px
    conv = lambda pts: [(round(x * sx, 2), round(y * sy, 2)) for x, y in pts]  # noqa: E731
    kind = {"entrance": "entrance", "exit": "exit", "emergency_egress": "emergency_exit"}
    return SiteModel(
        id=m.venue_id, name=m.venue_name, width_m=m.world_width_meters, height_m=m.world_height_meters,
        walkable=conv(m.walkable_polygon),
        obstacles=[Obstacle(id=o.id, name=o.name, polygon=conv(o.polygon)) for o in m.obstacles],
        zones=[SiteZone(id=z.id, name=z.name, polygon=conv(z.polygon), capacity=z.capacity) for z in m.zones],
        portals=[Portal(id=p.id, name=p.name, kind=kind.get(p.portal_type, "exit"), a=conv([p.line[0]])[0], b=conv([p.line[1]])[0])
                 for p in m.portals],
    )


def zone_centroid(z: SiteZone) -> Pt:
    return polygon_centroid(z.polygon)
