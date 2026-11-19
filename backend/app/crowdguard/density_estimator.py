"""Occupancy, density and data-quality estimation for one zone reading.

Three kinds of number are kept apart everywhere:
  * ``observed``  – what a detector actually saw (people visible in the frame); a measurement, not ground truth.
  * ``estimate``  – the observed count corrected for expected occlusion, with an interval.
  * ``synthetic`` – values produced by the simulator (labelled through ``value_kind``).

Feed states are explicit. ``missing``/``stale`` feeds and ``detector_error`` never
become an occupancy of zero: the last known estimate is carried forward with a
widening interval and the zone is flagged, or the zone is reported ``unknown``.

The occlusion model and every threshold are illustrative defaults. They must be
calibrated against manual counts for a real venue and camera.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

FeedStatus = Literal["ok", "stale", "missing", "detector_error"]
BANDS = ["normal", "elevated", "high", "critical"]
BAND_RANK = {"unknown": -1, "normal": 0, "elevated": 1, "high": 2, "critical": 3}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "elevated_pct": 70, "high_pct": 85, "critical_pct": 100,
    "density_warn": 3.5, "density_critical": 4.5,
    "stale_after_s": 90, "min_confidence": 0.45,
}

# Occlusion model: expected detector recall falls as density rises (people hide each other).
RECALL_MAX, RECALL_MIN, RECALL_SLOPE = 0.95, 0.55, 0.07
RECALL_UNCERTAINTY = 0.08
# A carried-forward value loses confidence with a 2-minute time constant.
STALE_DECAY_S = 120.0


def expected_recall(density_ppm2: float) -> float:
    return max(RECALL_MIN, min(RECALL_MAX, RECALL_MAX - RECALL_SLOPE * max(0.0, density_ppm2)))


def occlusion_corrected(observed: int, area_m2: float) -> dict[str, Any]:
    """Estimate true occupancy from a visible count by solving est = observed / recall(est / area)."""
    observed = max(0, int(observed))
    est = float(observed)
    for _ in range(8):
        est = observed / expected_recall(est / area_m2)
    r = expected_recall(est / area_m2)
    r_hi, r_lo = min(0.99, r + RECALL_UNCERTAINTY), max(0.3, r - RECALL_UNCERTAINTY)
    noise = 1.96 * math.sqrt(max(observed, 1))  # counting noise (Poisson-like)
    lower = max(observed, (observed - noise) / r_hi) if observed else 0.0
    upper = (observed + noise) / r_lo
    return {"estimate": round(est), "lower": int(math.floor(lower)), "upper": int(math.ceil(upper)),
            "recall_assumed": round(r, 3)}


def occupancy_band(pct: float | None, density: float | None, th: dict[str, float] | None = None) -> str:
    th = {**DEFAULT_THRESHOLDS, **(th or {})}
    if pct is None:
        return "unknown"
    band = "normal"
    if pct >= th["elevated_pct"]:
        band = "elevated"
    if pct >= th["high_pct"]:
        band = "high"
    if pct >= th["critical_pct"]:
        band = "critical"
    if density is not None:
        if density >= th["density_critical"]:
            band = "critical"
        elif density >= th["density_warn"] and BAND_RANK[band] < BAND_RANK["high"]:
            band = "high"
    return band


def level_of_service(density: float | None) -> str | None:
    """Fruin-style level of service for standing/queuing areas (persons per m²)."""
    if density is None:
        return None
    for limit, los in ((0.83, "A"), (1.08, "B"), (1.54, "C"), (3.57, "D"), (5.0, "E")):
        if density < limit:
            return los
    return "F"


def quality_label(conf: float | None) -> str:
    if conf is None or conf <= 0:
        return "unavailable"
    return "good" if conf >= 0.7 else "fair" if conf >= 0.45 else "poor"


@dataclass
class Observation:
    """One sensor reading for one zone."""

    zone_id: str
    t: float                               # seconds since scenario/clip start
    feed_status: FeedStatus = "ok"
    observed_count: int | None = None      # people visible (None when no usable frame)
    detector_confidence: float | None = None  # mean detection confidence (0-1)
    tracking_stability: float | None = None   # 0-1, 1 = no fragmentation (None = not tracked)
    source: str = "simulation"             # simulation | video | image | manual
    value_kind: str = "synthetic"          # synthetic | measured
    coverage: float = 1.0                  # fraction of the zone area the camera sees (extrapolation if < 1)
    synthetic_truth: int | None = None     # simulation only: the hidden "true" value, for evaluation


def assess_reading(zone, obs: Observation, previous: dict[str, Any] | None = None,
                   thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """Turn an observation into an occupancy reading with explicit uncertainty and quality.

    ``zone`` needs ``id``, ``area_m2`` and ``safe_capacity``. ``previous`` is the last reading for the
    zone (used only to carry a value forward when the feed is unusable).
    """
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    cap, area = zone.safe_capacity, zone.area_m2
    notes: list[str] = []
    reading: dict[str, Any] = {
        "zone_id": zone.id, "t": obs.t, "source": obs.source, "value_kind": obs.value_kind,
        "feed_status": obs.feed_status, "observed_count": obs.observed_count, "safe_capacity": cap,
        "area_m2": area, "coverage": obs.coverage,
    }
    usable = obs.feed_status == "ok" and obs.observed_count is not None
    if usable:
        visible_area = max(area * max(min(obs.coverage, 1.0), 1e-6), 1e-6)
        corr = occlusion_corrected(obs.observed_count, visible_area)
        scale = 1.0 / max(min(obs.coverage, 1.0), 1e-6)
        est, lo, hi = corr["estimate"] * scale, corr["lower"] * scale, corr["upper"] * scale
        if obs.coverage < 1.0:
            # Extrapolating from a partial view: widen the interval for spatial non-uniformity.
            spread = 0.5 * (1 - obs.coverage)
            lo, hi = lo * (1 - spread), hi * (1 + spread)
            notes.append(f"Extrapolated from a camera view covering {obs.coverage:.0%} of the zone")
        det_c = obs.detector_confidence if obs.detector_confidence is not None else 0.9
        trk_c = obs.tracking_stability if obs.tracking_stability is not None else 1.0
        conf = det_c * (0.4 + 0.6 * corr["recall_assumed"]) * (0.7 + 0.3 * trk_c) * (0.35 + 0.65 * min(obs.coverage, 1.0))
        reading.update(estimate=int(round(est)), lower=int(math.floor(lo)), upper=int(math.ceil(hi)),
                       recall_assumed=corr["recall_assumed"], age_s=0.0, carried_forward=False,
                       method="occlusion-corrected detector count" if obs.source != "simulation"
                       else "occlusion-corrected synthetic sensor count")
        if obs.observed_count == 0:
            notes.append("Detector ran and saw nobody: zero is a measurement here, not a missing value")
    else:
        prev_ok = previous if previous and previous.get("estimate") is not None else None
        if obs.feed_status == "detector_error":
            notes.append("Frames arrived but person detection failed: occupancy unknown (not zero)")
        elif obs.feed_status in ("stale", "missing"):
            notes.append("No fresh camera data: occupancy unknown (a missing feed is never treated as an empty zone)")
        if prev_ok:
            base_t = prev_ok["t"] - (prev_ok.get("age_s") or 0.0)
            age = max(0.0, obs.t - base_t)
            # Uncertainty grows with age: allow ±(3% of capacity per minute) drift.
            drift = cap * 0.03 * (age / 60.0)
            conf = (prev_ok.get("confidence") or 0.5) * math.exp(-age / STALE_DECAY_S)
            reading.update(estimate=prev_ok["estimate"], lower=int(max(0, prev_ok["lower"] - drift)),
                           upper=int(prev_ok["upper"] + drift), recall_assumed=prev_ok.get("recall_assumed"),
                           age_s=round(age, 1), carried_forward=True,
                           method=f"last known value carried forward ({age:.0f} s old)")
            if obs.feed_status == "ok":  # observed_count None with ok status: treat as stale
                reading["feed_status"] = "stale"
        else:
            conf = 0.0
            reading.update(estimate=None, lower=None, upper=None, recall_assumed=None, age_s=None,
                           carried_forward=False, method="no data")
    est = reading.get("estimate")
    reading["occupancy_pct"] = round(est / cap * 100, 1) if est is not None else None
    reading["upper_pct"] = round(reading["upper"] / cap * 100, 1) if reading.get("upper") is not None else None
    reading["density_ppm2"] = round(est / area, 3) if est is not None else None
    reading["level_of_service"] = level_of_service(reading["density_ppm2"])
    stale_too_long = (reading.get("age_s") or 0) > th["stale_after_s"] * 3
    reading["band"] = "unknown" if est is None or stale_too_long else occupancy_band(
        reading["occupancy_pct"], reading["density_ppm2"], th)
    reading["confidence"] = round(max(0.0, min(1.0, conf)), 3)
    reading["data_quality"] = quality_label(reading["confidence"]) if est is not None else "unavailable"
    reading["spare_capacity"] = int(cap - reading["upper"]) if reading.get("upper") is not None else None
    reading["notes"] = notes
    if obs.synthetic_truth is not None:
        reading["synthetic_truth"] = obs.synthetic_truth
    return reading
