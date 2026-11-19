"""Zone definitions, polygon geometry and per-zone population counting.

Detections are assigned to zones by their *foot point* (bottom-centre of the
box), which is the person's contact with the ground plane and is much less
sensitive to perspective than the box centre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

Point = tuple[float, float]


def polygon_area(poly: Sequence[Sequence[float]]) -> float:
    """Shoelace formula (absolute area, same units as the vertices squared)."""
    n = len(poly)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(poly: Sequence[Sequence[float]]) -> Point:
    n = len(poly)
    a = 0.0
    cx = cy = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:  # degenerate: fall back to the vertex mean
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))


def _on_segment(p: Point, a: Sequence[float], b: Sequence[float], eps: float = 1e-9) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > eps * max(1.0, abs(bx - ax) + abs(by - ay)):
        return False
    return min(ax, bx) - eps <= px <= max(ax, bx) + eps and min(ay, by) - eps <= py <= max(ay, by) + eps


def point_in_polygon(p: Point, poly: Sequence[Sequence[float]]) -> bool:
    """Ray casting. Points on an edge or vertex count as inside (deterministic tie-break)."""
    n = len(poly)
    if n < 3:
        return False
    x, y = p
    inside = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if _on_segment(p, a, b):
            return True
        (x1, y1), (x2, y2) = a, b
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: tuple[Point, ...]
    area_m2: float
    safe_capacity: int
    kind: str = "general"
    camera_id: str | None = None
    venue_zone: str | None = None   # for camera-space zones: which venue zone they observe
    service_rate_ppm: float | None = None  # queue zones: people served per minute
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def centroid(self) -> Point:
        return polygon_centroid(self.polygon)

    @property
    def polygon_area(self) -> float:
        return polygon_area(self.polygon)

    def contains(self, p: Point) -> bool:
        return point_in_polygon(p, self.polygon)

    def describe(self) -> dict[str, Any]:
        cx, cy = self.centroid
        return {"id": self.id, "name": self.name, "kind": self.kind, "polygon": [list(p) for p in self.polygon],
                "area_m2": self.area_m2, "safe_capacity": self.safe_capacity, "camera_id": self.camera_id,
                "venue_zone": self.venue_zone, "service_rate_ppm": self.service_rate_ppm,
                "centroid": [round(cx, 2), round(cy, 2)],
                "safe_density_ppm2": round(self.safe_capacity / self.area_m2, 3) if self.area_m2 else None}


def zone_from_config(cfg: dict[str, Any]) -> Zone:
    poly = tuple((float(x), float(y)) for x, y in cfg["polygon"])
    if len(poly) < 3:
        raise ValueError(f"Zone '{cfg.get('id')}' needs at least 3 polygon vertices")
    if polygon_area(poly) <= 0:
        raise ValueError(f"Zone '{cfg.get('id')}' polygon has zero area")
    area = float(cfg.get("area_m2") or 0)
    cap = int(cfg.get("safe_capacity") or 0)
    if area <= 0 or cap <= 0:
        raise ValueError(f"Zone '{cfg.get('id')}' needs a positive area_m2 and safe_capacity")
    return Zone(id=str(cfg["id"]), name=str(cfg.get("name", cfg["id"])), polygon=poly, area_m2=area, safe_capacity=cap,
                kind=str(cfg.get("kind", "general")), camera_id=cfg.get("camera_id"), venue_zone=cfg.get("venue_zone"),
                service_rate_ppm=cfg.get("service_rate_ppm"),
                extra={"coverage": cfg.get("coverage")} if cfg.get("coverage") is not None else {})


class ZoneManager:
    """Holds a set of polygon zones and assigns points to them.

    Overlapping zones are resolved deterministically: the smallest polygon
    (the most specific zone) wins, then the earliest-declared one.
    """

    UNZONED = "_unzoned"

    def __init__(self, zones: Iterable[Zone]) -> None:
        self.zones: list[Zone] = list(zones)
        ids = [z.id for z in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("Zone ids must be unique")
        self._by_id = {z.id: z for z in self.zones}
        self._order = sorted(range(len(self.zones)), key=lambda i: (self.zones[i].polygon_area, i))

    @classmethod
    def from_config(cls, zone_cfgs: Iterable[dict[str, Any]]) -> "ZoneManager":
        return cls(zone_from_config(c) for c in zone_cfgs)

    def get(self, zone_id: str) -> Zone | None:
        return self._by_id.get(zone_id)

    def ids(self) -> list[str]:
        return [z.id for z in self.zones]

    def assign(self, p: Point) -> str | None:
        for i in self._order:
            if self.zones[i].contains(p):
                return self.zones[i].id
        return None

    def assign_many(self, points: Iterable[Point]) -> list[str | None]:
        return [self.assign(p) for p in points]

    def count(self, points: Iterable[Point]) -> dict[str, int]:
        """Population per zone for one instant. Every zone appears (zero included) plus an unzoned bucket."""
        out = {z.id: 0 for z in self.zones}
        out[self.UNZONED] = 0
        for p in points:
            zid = self.assign(p)
            out[zid if zid is not None else self.UNZONED] += 1
        return out

    def describe(self) -> list[dict[str, Any]]:
        return [z.describe() for z in self.zones]
