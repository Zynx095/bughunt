"""Short-horizon occupancy forecasting with explicit uncertainty and a deterministic fallback.

``forecast_zone`` is fast and fully deterministic (no randomness, no training state), so the same
history always gives the same forecast. Method by history length:
  * < 3 points   – persistence (flat) with a wide band: there is not enough data to see a trend.
  * < 8 points   – least-squares linear trend over the available points.
  * otherwise    – damped Holt (double exponential smoothing); the band comes from the one-step
                   residuals and widens with the horizon.
The richer, backtested model selection lives in the ML engine (``ml.forecast``); the crowd engine
calls it through the registry when enough history exists and shows both side by side.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

Z95 = 1.96


def _holt_damped(y: np.ndarray, alpha: float = 0.5, beta: float = 0.3, phi: float = 0.9) -> tuple[float, float, np.ndarray]:
    level, trend = float(y[0]), float(y[1] - y[0])
    resid = []
    for v in y[1:]:
        pred = level + phi * trend
        resid.append(v - pred)
        new_level = alpha * v + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return level, trend, np.asarray(resid)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def forecast_zone(history: Sequence[float | None], capacity: float, horizon: int = 15, step_minutes: float = 1.0,
                  floor_sigma_frac: float = 0.01, max_value: float | None = None) -> dict[str, Any]:
    """Forecast the next ``horizon`` steps of a zone's occupancy estimate."""
    y = np.array([v for v in history if v is not None], dtype=float)
    n = len(y)
    if n == 0:
        return {"available": False, "method": "no history", "reason": "no occupancy estimates yet", "horizon": horizon}
    hs = np.arange(1, horizon + 1, dtype=float)
    floor_sigma = max(1.0, capacity * floor_sigma_frac)
    if n < 3:
        method = "persistence (insufficient history)"
        point = np.full(horizon, y[-1])
        sigma_h = np.maximum(floor_sigma, capacity * 0.05) * np.sqrt(hs)
    elif n < 8:
        method = "linear trend (short history)"
        x = np.arange(n, dtype=float)
        slope, icpt = np.polyfit(x, y, 1)
        point = icpt + slope * (n - 1 + hs)
        resid = y - (icpt + slope * x)
        sigma = max(floor_sigma, float(np.std(resid, ddof=1)) if n > 2 else floor_sigma)
        sigma_h = sigma * np.sqrt(hs) * 1.5  # extra width: the trend itself is uncertain with few points
    else:
        method = "damped Holt trend"
        phi = 0.9
        level, trend, resid = _holt_damped(y, phi=phi)
        damp = np.array([sum(phi ** k for k in range(1, int(h) + 1)) for h in hs])
        point = level + damp * trend
        recent = resid[-20:]
        sigma = max(floor_sigma, float(np.std(recent, ddof=1)) if len(recent) > 2 else floor_sigma)
        sigma_h = sigma * np.sqrt(hs)
    upper_cap = max_value if max_value is not None else None
    point = np.maximum(point, 0.0)
    lower = np.maximum(point - Z95 * sigma_h, 0.0)
    upper = point + Z95 * sigma_h
    if upper_cap is not None:
        point, upper = np.minimum(point, upper_cap), np.minimum(upper, upper_cap)

    def first_cross(series: np.ndarray) -> float | None:
        idx = np.nonzero(series >= capacity)[0]
        return float(hs[idx[0]] * step_minutes) if len(idx) else None

    current = float(y[-1])
    peak_i = int(np.argmax(point))
    sig_end = float(sigma_h[-1]) or 1.0
    p_exceed = 1 - _norm_cdf((capacity - float(point[-1])) / sig_end)
    return {
        "available": True, "method": method, "history_points": n, "horizon": horizon, "step_minutes": step_minutes,
        "forecast": [int(round(v)) for v in point], "lower": [int(round(v)) for v in lower], "upper": [int(round(v)) for v in upper],
        "current": int(round(current)), "current_pct": round(current / capacity * 100, 1),
        "predicted_end": int(round(point[-1])), "predicted_end_pct": round(float(point[-1]) / capacity * 100, 1),
        "peak": int(round(point[peak_i])), "peak_pct": round(float(point[peak_i]) / capacity * 100, 1),
        "peak_in_min": float(hs[peak_i] * step_minutes),
        "delta_vs_current": int(round(point[-1] - current)),
        "minutes_to_capacity": first_cross(point),          # central forecast reaches safe capacity
        "minutes_to_possible_breach": first_cross(upper),   # upper band reaches safe capacity
        "p_exceed_at_horizon": round(p_exceed, 3),
        "p_note": "heuristic: normal approximation of the forecast error; not a calibrated probability",
    }


def rolling_backtest(series: Sequence[float], capacity: float, horizon: int = 10, min_history: int = 8,
                     stride: int = 1) -> dict[str, Any]:
    """Rolling-origin evaluation: forecast from each origin using only past data, compare with what happened.
    Reports MAE of the method against a persistence (last value) baseline at the given horizon."""
    y = [float(v) for v in series]
    errs, base_errs, rows = [], [], []
    for origin in range(min_history, len(y) - horizon, stride):
        fc = forecast_zone(y[: origin + 1], capacity, horizon=horizon)
        pred = fc["forecast"][-1]
        actual = y[origin + horizon]
        errs.append(abs(pred - actual))
        base_errs.append(abs(y[origin] - actual))
        rows.append({"origin": origin, "predicted": pred, "actual": round(actual), "persistence": round(y[origin])})
    if not errs:
        return {"available": False, "reason": "series too short for a rolling backtest"}
    mae, base = float(np.mean(errs)), float(np.mean(base_errs))
    return {"available": True, "horizon": horizon, "origins": len(errs), "mae": round(mae, 1), "baseline": "persistence",
            "baseline_mae": round(base, 1), "beats_baseline": mae < base,
            "mae_pct_of_capacity": round(mae / capacity * 100, 2), "rows": rows}
