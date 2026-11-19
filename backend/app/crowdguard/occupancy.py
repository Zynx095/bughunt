"""Spatial occupancy: where people are, and where they are not.

From ground-plane person positions (with per-person uncertainty) this computes, for every site cell:
  * a Gaussian-KDE density (persons/m² when the calibration is confirmed, otherwise a relative index),
  * a state:  A available · O occupied · C congested · B blocked · U unknown,
  * the free (usable) floor area,
and per-zone population, density, occupancy band and mean speed.

Unknown is never treated as empty: cells the camera cannot see, and every cell while the feed is
unavailable or detection failed, are 'U'. Blocked cells (obstacles, outside the walkable area,
restricted zones) are 'B' regardless of who is standing near them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from .density_estimator import DEFAULT_THRESHOLDS, occupancy_band
from .site_model import SiteMasks, SiteModel
from .zone_manager import point_in_polygon

PERSON_FOOTPRINT_M2 = 0.5  # standing space one person needs (body + minimal buffer)


@dataclass
class GroundPerson:
    x: float
    y: float
    weight: float = 1.0          # < 1 while a track is only predicted (occluded / missed)
    sigma: float = 0.8           # positional uncertainty (metres), feeds the KDE bandwidth
    speed: Optional[float] = None
    track_id: Optional[int] = None


def kde_density(site: SiteModel, people: list[GroundPerson]) -> np.ndarray:
    """Gaussian KDE evaluated at cell centres; integrates to the (weighted) number of people."""
    centers = site.cell_centers().reshape(-1, 2)
    dens = np.zeros(len(centers))
    for p in people:
        s = max(site.kde_sigma_m, p.sigma)
        d2 = (centers[:, 0] - p.x) ** 2 + (centers[:, 1] - p.y) ** 2
        dens += p.weight * np.exp(-d2 / (2 * s * s)) / (2 * math.pi * s * s)
    return dens.reshape(site.rows, site.cols)


def compute_occupancy(site: SiteModel, masks: SiteMasks, people: list[GroundPerson], visible: np.ndarray,
                      feed_ok: bool, metric: bool) -> dict[str, Any]:
    rows, cols = site.rows, site.cols
    cell_area = site.cell_m ** 2
    density = kde_density(site, people) if feed_ok else np.zeros((rows, cols))
    counts = np.zeros((rows, cols))
    for p in people:
        if 0 <= p.x < site.width_m and 0 <= p.y < site.height_m:
            r, c = site.cell_of((p.x, p.y))
            counts[r, c] += p.weight

    observed = visible & feed_ok
    state = np.full((rows, cols), "A", dtype="<U1")
    state[(density >= site.occupied_density) | (counts >= 0.5)] = "O"
    state[density >= site.congested_density] = "C"
    state[~observed] = "U"
    state[masks.blocked] = "B"

    persons_equiv = density * cell_area
    free = np.clip(cell_area - persons_equiv * PERSON_FOOTPRINT_M2, 0, cell_area)
    free[(state == "B") | (state == "U")] = 0.0

    def area(code: str) -> float:
        return round(float(np.count_nonzero(state == code)) * cell_area, 1)

    walk_obs = (~masks.blocked) & observed
    summary = {
        "available_m2": area("A"), "occupied_m2": area("O"), "congested_m2": area("C"),
        "blocked_m2": area("B"), "unknown_m2": area("U"),
        "free_space_m2": round(float(free.sum()), 1),
        "observed_walkable_m2": round(float(np.count_nonzero(walk_obs)) * cell_area, 1),
        "observed_fraction": round(float(np.count_nonzero(walk_obs)) / max(1, int(np.count_nonzero(~masks.blocked))), 3),
        "peak": round(float(density[walk_obs].max()), 3) if walk_obs.any() else None,
        "people_in_view": round(float(sum(p.weight for p in people)), 1) if feed_ok else None,
    }

    zones = []
    th = DEFAULT_THRESHOLDS
    for zi, z in enumerate(site.zones):
        zmask = masks.zone_of == zi
        zcells = int(np.count_nonzero(zmask))
        seen = int(np.count_nonzero(zmask & observed))
        vis_frac = seen / zcells if zcells else 0.0
        inside = [p for p in people if point_in_polygon((p.x, p.y), z.polygon)]
        count = sum(p.weight for p in inside)
        area_m2 = z.area_m2
        cap = z.capacity or max(1, int(area_m2 * 2.0))
        speeds = [p.speed for p in inside if p.speed is not None]
        if not feed_ok or vis_frac == 0 or z.restricted:
            pop, pct, band = None, None, "unknown" if not z.restricted else "restricted"
        else:
            pop = round(count, 1)
            pct = round(count / cap * 100, 1)
            band = occupancy_band(pct, count / area_m2 if metric else None, th)
        zones.append({
            "id": z.id, "name": z.name, "restricted": z.restricted, "capacity": cap, "area_m2": round(area_m2, 1),
            "population": pop, "occupancy_pct": pct, "band": band,
            "density": round(count / area_m2, 3) if (pop is not None and metric) else None,
            "density_index": round(count / area_m2 / site.congested_density, 3) if pop is not None else None,
            "mean_speed": round(float(np.mean(speeds)), 2) if (speeds and pop is not None) else None,
            "visible_fraction": round(vis_frac, 2),
            "note": None if vis_frac >= 0.95 or pop is None else f"Only {vis_frac:.0%} of this zone is in view: count covers the visible part",
        })

    return {
        "rows": rows, "cols": cols, "cell_m": site.cell_m,
        "state": "".join(state.reshape(-1)),
        # Density: p/m² when metric, otherwise relative to the congestion threshold (1.0 = congested).
        "unit": "persons/m²" if metric else "relative (1.0 = congestion threshold)",
        "values": [round(float(v), 3) for v in (density if metric else density / site.congested_density).reshape(-1)],
        "free_m2": [round(float(v), 3) for v in free.reshape(-1)],
        "summary": summary, "zones": zones,
        "_density": density, "_state": state,  # internal (not serialised)
    }
