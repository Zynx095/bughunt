"""Smart city & mobility: junction congestion monitoring and forecasting."""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table, tone_for_band


class Reading(BaseModel):
    timestamp: str
    vehicles: float = Field(..., ge=0)
    avg_speed_kmh: float = Field(..., ge=0)


class Input(BaseModel):
    junction: str
    capacity_per_hour: float = Field(..., gt=0)
    horizon_hours: int = Field(24, ge=1, le=168)
    readings: list[Reading] = Field(..., min_length=24 * 14, max_length=50_000, description="Hourly; at least two weeks for weekly seasonality")


RULES = [
    {"id": "over-capacity", "description": "Forecast peak at or above 90% of junction capacity", "severity": "high",
     "outcome": "activate_adaptive_signal_plan", "when": {"field": "peak_utilisation", "op": "gte", "value": 0.9}},
    {"id": "recent-anomaly", "description": "Anomalous flow detected in the last 24 hours", "severity": "medium",
     "outcome": "dispatch_field_check", "when": {"field": "recent_anomalies", "op": "gte", "value": 1}},
    {"id": "near-capacity", "description": "Forecast peak between 75% and 90% of capacity", "severity": "low",
     "outcome": "monitor_closely", "when": {"field": "peak_utilisation", "op": "between", "value": [0.75, 0.9]}},
]


def _facts(pc: PipelineContext) -> dict:
    fc, cap = pc.r("forecast"), pc.input["capacity_per_hour"]
    peak = max(fc["forecast"])
    rows = pc.r("anomaly")["rows"]
    recent = sum(1 for r in rows[-24:] if r["is_anomaly"])
    pc.vars.update(peak=peak, peak_util=peak / cap, recent=recent)
    return {"rules": RULES, "default_outcome": "normal_operations",
            "facts": {"peak_utilisation": round(peak / cap, 3), "recent_anomalies": recent}}


def present(pc: PipelineContext) -> dict:
    readings, fc, an = pc.input["readings"], pc.r("forecast"), pc.r("anomaly")
    last = datetime.fromisoformat(readings[-1]["timestamp"])
    hist = readings[-72:]
    flagged = {r["index"] for r in an["rows"] if r["is_anomaly"]}
    offset = len(readings) - len(hist)
    data = [{"t": r["timestamp"][5:16].replace("T", " "), "actual": r["vehicles"],
             "anomaly": r["vehicles"] if (offset + i) in flagged else None} for i, r in enumerate(hist)]
    for h, (v, lo, hi) in enumerate(zip(fc["forecast"], fc["lower"], fc["upper"]), start=1):
        data.append({"t": (last + timedelta(hours=h)).isoformat()[5:16].replace("T", " "), "forecast": round(v),
                     "lower": round(max(0, lo)), "upper": round(hi)})
    peak_i = max(range(len(fc["forecast"])), key=lambda i: fc["forecast"][i])
    peak_at = (last + timedelta(hours=peak_i + 1)).strftime("%a %H:%M")
    bt = fc["backtest"]
    decision = pc.r("policy")
    anomalies = [{"timestamp": readings[r["index"]]["timestamp"].replace("T", " "), "vehicles": readings[r["index"]]["vehicles"],
                  "speed": readings[r["index"]]["avg_speed_kmh"], "score": r["anomaly_score"],
                  "why": ", ".join(f"{d['feature']} z={d['robust_z']}" for d in r["top_deviations"]) or "multivariate pattern"}
                 for r in an["rows"] if r["is_anomaly"]]
    util = pc.vars["peak_util"]
    return {
        "headline": f"{pc.input['junction']}: forecast peak {round(pc.vars['peak'])} veh/h ({util:.0%} of capacity) at {peak_at}; action: {decision['outcome']}",
        "metrics": [
            metric("Forecast peak", f"{round(pc.vars['peak'])} veh/h", tone_for_band("high" if util >= .9 else "medium" if util >= .75 else "low"), hint=peak_at),
            metric("Capacity use at peak", f"{util:.0%}"),
            metric("Anomalous hours", an["anomaly_count"], "warn" if an["anomaly_count"] else "good"),
            metric("Backtest MAE", f"{bt['model_mae']:.0f}", "good" if bt["beats_baseline"] else "warn",
                   hint=f"baseline ({bt['baseline']}) MAE {bt['baseline_mae']:.0f}"),
            metric("Decision", decision["outcome"].replace("_", " "), tone_for_band(decision["max_severity"])),
        ],
        "charts": [chart("line", "Vehicles per hour — last 72 h and forecast", data, "t",
                         [("actual", "Observed"), ("forecast", "Forecast"), ("upper", "Upper ~95%"), ("lower", "Lower ~95%"), ("anomaly", "Anomaly")],
                         reference_lines=[{"y": pc.input["capacity_per_hour"], "label": "capacity"}])],
        "tables": [table("Anomalous readings", [("timestamp", "Time"), ("vehicles", "Vehicles"), ("speed", "Speed km/h"),
                                                ("score", "Score"), ("why", "Deviation")], anomalies)],
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["Demo readings are synthetic. Backtest compares the model with a seasonal-naive baseline on held-out hours."],
    }


ADAPTER = DomainAdapter(
    id="smart_city", name="Smart City & Mobility", icon="TrafficCone", color="#0284c7",
    tagline="Detect abnormal traffic flow and forecast junction congestion before it happens",
    description="Profiles sensor readings, derives time features, flags anomalous hours (incidents, sensor dropouts) with Isolation Forest, forecasts the next day with a seasonal model backtested against a naive baseline, and applies operating rules.",
    scenario="Junction congestion early warning", impact="Gives operators hours of warning to retime signals or dispatch crews.",
    input_model=Input, sample_file="smart_city.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("profile", "Profile readings", "data", "profile", build=lambda pc: {"records": pc.input["readings"]},
             why="Data-quality check: types, gaps, ranges"),
        Step("features", "Time features", "data", "extract_features",
             build=lambda pc: {"records": pc.input["readings"], "datetime_columns": ["timestamp"]}, why="Hour/day features for context-aware anomaly detection"),
        Step("anomaly", "Anomaly detection", "ml", "anomaly",
             build=lambda pc: {"records": pc.r("features")["records"], "id_field": "timestamp", "contamination": 0.02,
                               "features": ["vehicles", "avg_speed_kmh", "timestamp_hour", "timestamp_is_weekend"]},
             why="Incidents and sensor faults break the usual hour-of-day pattern"),
        Step("forecast", "Congestion forecast", "ml", "forecast",
             build=lambda pc: {"values": [r["vehicles"] for r in pc.input["readings"]], "horizon": pc.input["horizon_hours"], "season_length": 168},
             why="Weekly-seasonal model selection, backtested against seasonal-naive"),
        Step("policy", "Operating rules", "decision", "evaluate_rules", build=_facts, why="Deterministic operator actions"),
        Step("explain", "Operator briefing", "ai", "explain", optional=True,
             build=lambda pc: {"subject": f"Junction {pc.input['junction']}", "audience": "executive", "context": {
                 "outcome": pc.r("policy")["outcome"], "matched": pc.r("policy")["matched"],
                 "forecast_peak_vehicles_per_hour": round(pc.vars["peak"]), "capacity_per_hour": pc.input["capacity_per_hour"],
                 "anomalous_hours_last_24h": pc.vars["recent"], "backtest_mae": pc.r("forecast")["backtest"]["model_mae"]}}),
    ],
)
