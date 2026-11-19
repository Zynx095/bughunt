"""Crowd movement: velocities from tracks, per-zone flow statistics, and density-speed relations.

Speeds from video are in pixels/second unless a ``meters_per_pixel`` calibration is given; the
output always states which unit applies. Speeds in the simulation come from the Weidmann
fundamental diagram (walking speed falls as density rises).
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

from .crowd_tracking import TrackHistory

FREE_SPEED_MPS = 1.34      # Weidmann (1993) free walking speed
JAM_DENSITY = 5.4          # persons/m² at which flow stops
COMPASS = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]


def walking_speed(density: float | None) -> float | None:
    """Weidmann's fundamental diagram: v(ρ) = v0 · (1 − exp(−1.913 · (1/ρ − 1/ρmax)))."""
    if density is None:
        return None
    if density <= 0.05:
        return FREE_SPEED_MPS
    if density >= JAM_DENSITY:
        return 0.05
    return max(0.05, FREE_SPEED_MPS * (1 - math.exp(-1.913 * (1 / density - 1 / JAM_DENSITY))))


def specific_flow(density: float | None) -> float | None:
    """Persons per metre width per second = ρ · v(ρ)."""
    v = walking_speed(density)
    return None if v is None else density * v


def heading_deg(vx: float, vy: float) -> float:
    """Heading in degrees with 0 = east, 90 = north (image y grows downward, so it is flipped)."""
    return (math.degrees(math.atan2(-vy, vx)) + 360.0) % 360.0


def compass(deg: float) -> str:
    return COMPASS[int(((deg + 22.5) % 360) // 45)]


def track_velocities(history: TrackHistory, window_s: float = 1.5, meters_per_pixel: float | None = None,
                     min_span_s: float = 0.3) -> list[dict[str, Any]]:
    """Velocity of each track over its last ``window_s`` seconds (least-squares slope of position)."""
    out = []
    for tid, pts in history.points.items():
        if len(pts) < 2:
            continue
        t_end = pts[-1].t
        recent = [p for p in pts if p.t >= t_end - window_s]
        if len(recent) < 2:
            recent = pts[-2:]
        ts = np.array([p.t for p in recent])
        if ts.max() - ts.min() < min_span_s:
            continue
        xs, ys = np.array([p.x for p in recent]), np.array([p.y for p in recent])
        vx = float(np.polyfit(ts, xs, 1)[0])
        vy = float(np.polyfit(ts, ys, 1)[0])
        scale = meters_per_pixel or 1.0
        vx, vy = vx * scale, vy * scale
        speed = math.hypot(vx, vy)
        out.append({"track_id": tid, "vx": round(vx, 4), "vy": round(vy, 4), "speed": round(speed, 4),
                    "heading_deg": round(heading_deg(vx, vy), 1), "zone": recent[-1].zone,
                    "unit": "m/s" if meters_per_pixel else "px/s"})
    return out


def direction_histogram(velocities: Iterable[dict[str, Any]], bins: int = 8, min_speed: float = 0.0) -> list[dict[str, Any]]:
    counts = [0] * bins
    width = 360.0 / bins
    for v in velocities:
        if v["speed"] <= min_speed:
            continue
        counts[int(((v["heading_deg"] + width / 2) % 360) // width)] += 1
    labels = COMPASS if bins == 8 else [f"{int(i * width)}°" for i in range(bins)]
    return [{"direction": labels[i], "count": c} for i, c in enumerate(counts)]


def flow_stats(velocities: Sequence[dict[str, Any]], stationary_speed: float) -> dict[str, Any]:
    """Mean/median speed, dominant direction, coherence (0 = chaotic, 1 = everyone moving the same way),
    share of stationary people and share moving against the dominant direction (counter-flow)."""
    if not velocities:
        return {"n": 0, "mean_speed": None, "median_speed": None, "dominant_heading_deg": None, "dominant_direction": None,
                "coherence": None, "stationary_fraction": None, "counterflow_fraction": None}
    speeds = np.array([v["speed"] for v in velocities])
    moving = [v for v in velocities if v["speed"] > stationary_speed]
    if moving:
        ux = np.array([v["vx"] / v["speed"] for v in moving])
        uy = np.array([v["vy"] / v["speed"] for v in moving])
        mx, my = float(ux.mean()), float(uy.mean())
        coherence = math.hypot(mx, my)
        dom = heading_deg(mx, my)
        counter = sum(1 for a, b in zip(ux, uy) if (a * mx + b * my) / max(coherence, 1e-9) < -0.5)
        counter_frac = counter / len(moving)
    else:
        coherence, dom, counter_frac = 0.0, None, 0.0
    return {"n": len(velocities), "mean_speed": round(float(speeds.mean()), 4), "median_speed": round(float(np.median(speeds)), 4),
            "dominant_heading_deg": round(dom, 1) if dom is not None else None,
            "dominant_direction": compass(dom) if dom is not None else None,
            "coherence": round(coherence, 3), "stationary_fraction": round(1 - len(moving) / len(velocities), 3),
            "counterflow_fraction": round(counter_frac, 3)}


def zone_flow_stats(velocities: Sequence[dict[str, Any]], stationary_speed: float) -> dict[str, dict[str, Any]]:
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for v in velocities:
        if v.get("zone"):
            by_zone.setdefault(v["zone"], []).append(v)
    return {z: flow_stats(vs, stationary_speed) for z, vs in by_zone.items()}


def trend_per_minute(values: Sequence[float | None], step_minutes: float = 1.0, window: int = 5) -> float | None:
    """Least-squares slope over the last ``window`` non-null values, in units per minute."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None][-window:]
    if len(pts) < 2:
        return None
    xs = np.array([p[0] for p in pts], dtype=float) * step_minutes
    ys = np.array([p[1] for p in pts], dtype=float)
    if np.ptp(xs) == 0:
        return None
    return float(np.polyfit(xs, ys, 1)[0])


def unit_vector(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d


def zone_net_flow(zone_id: str, pos: dict[str, Sequence[float]], edge_flows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Net movement vector of a zone from directed edge flows (map coordinates, persons/min)."""
    vx = vy = 0.0
    inflow = outflow = 0.0
    for e in edge_flows:
        f = e.get("flow_ppm") or 0.0
        if f <= 0:
            continue
        if e["from"] == zone_id:
            ux, uy = unit_vector(pos[zone_id], pos[e["to"]])
            vx += f * ux
            vy += f * uy
            outflow += f
        elif e["to"] == zone_id:
            ux, uy = unit_vector(pos[e["from"]], pos[zone_id])
            vx += f * ux
            vy += f * uy
            inflow += f
    mag = math.hypot(vx, vy)
    return {"inflow_ppm": round(inflow, 1), "outflow_ppm": round(outflow, 1), "net_ppm": round(inflow - outflow, 1),
            "vector": [round(vx, 2), round(vy, 2)], "magnitude": round(mag, 2),
            "direction": compass(heading_deg(vx, vy)) if mag > 1e-6 else None}
