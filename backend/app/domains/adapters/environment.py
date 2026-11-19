"""Environment & sustainability: air-quality sensor QA and next-day PM2.5 outlook."""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table

# PM2.5 (24-h) AQI breakpoints following the US EPA 2024 revision. Configurable per deployment.
BANDS = [(9.0, "Good"), (35.4, "Moderate"), (55.4, "Unhealthy for sensitive groups"), (125.4, "Unhealthy"),
         (225.4, "Very unhealthy"), (float("inf"), "Hazardous")]


def category(pm: float) -> str:
    return next(name for limit, name in BANDS if pm <= limit)


class Reading(BaseModel):
    timestamp: str
    pm25: float | None = Field(None, ge=0, le=2000)
    temperature_c: float | None = None
    humidity_pct: float | None = Field(None, ge=0, le=100)
    wind_speed_ms: float | None = Field(None, ge=0)


class Input(BaseModel):
    station: str
    unit: str = "µg/m³"
    horizon_hours: int = Field(24, ge=1, le=168)
    readings: list[Reading] = Field(..., min_length=48, max_length=50_000)


RULES = [
    {"id": "unhealthy", "description": "Forecast 24-h mean in 'Unhealthy' band or worse (> 55.4)", "severity": "high",
     "outcome": "issue_public_health_advisory", "when": {"field": "forecast_mean", "op": "gt", "value": 55.4}},
    {"id": "sensitive", "description": "Forecast 24-h mean unhealthy for sensitive groups (35.5-55.4)", "severity": "medium",
     "outcome": "advise_sensitive_groups", "when": {"field": "forecast_mean", "op": "between", "value": [35.5, 55.4]}},
    {"id": "sensor-qa", "description": "Gaps or faulty spikes in the sensor feed", "severity": "low", "outcome": "schedule_sensor_maintenance",
     "when": {"any": [{"field": "gaps", "op": "gte", "value": 3}, {"field": "spikes", "op": "gte", "value": 1}]}},
]


def _qa(pc: PipelineContext) -> dict:
    """Flag isolated spikes (sensor faults) before forecasting: replace with neighbour median."""
    recs = pc.r("clean")["records"]
    vals = [r["pm25"] for r in recs]
    spikes = []
    for i in range(1, len(vals) - 1):
        neigh = sorted([vals[i - 1], vals[i + 1]])
        if vals[i] > 3 * max(neigh[1], 5) and vals[i] - neigh[1] > 40:
            spikes.append(i)
    series = list(vals)
    for i in spikes:
        series[i] = (vals[i - 1] + vals[i + 1]) / 2
    pc.vars.update(spikes=spikes, series=series, gaps=pc.r("clean")["report"]["missing_values_before"])
    return {"values": series, "horizon": pc.input["horizon_hours"], "season_length": 24}


def _facts(pc: PipelineContext) -> dict:
    fc = pc.r("forecast")["forecast"]
    mean24 = sum(fc[:24]) / min(24, len(fc))
    pc.vars["forecast_mean"] = mean24
    return {"rules": RULES, "default_outcome": "no_action",
            "facts": {"forecast_mean": round(mean24, 1), "gaps": pc.vars["gaps"], "spikes": len(pc.vars["spikes"])}}


def present(pc: PipelineContext) -> dict:
    recs, fc, an = pc.r("clean")["records"], pc.r("forecast"), pc.r("anomaly")
    last = datetime.fromisoformat(recs[-1]["timestamp"])
    hist = recs[-72:]
    off = len(recs) - len(hist)
    flagged = {r["index"] for r in an["rows"] if r["is_anomaly"]}
    data = [{"t": r["timestamp"][5:16].replace("T", " "), "pm25": r["pm25"],
             "flagged": r["pm25"] if (off + i) in flagged else None} for i, r in enumerate(hist)]
    for h, (v, lo, hi) in enumerate(zip(fc["forecast"], fc["lower"], fc["upper"]), start=1):
        data.append({"t": (last + timedelta(hours=h)).isoformat()[5:16].replace("T", " "), "forecast": round(v, 1),
                     "lower": round(max(0, lo), 1), "upper": round(hi, 1)})
    current = sum(r["pm25"] for r in recs[-24:]) / 24
    fmean = pc.vars["forecast_mean"]
    decision = pc.r("policy")
    bt = fc["backtest"]
    qa_rows = [{"timestamp": recs[i]["timestamp"].replace("T", " "), "pm25": recs[i]["pm25"], "issue": "isolated spike (likely sensor fault)"}
               for i in pc.vars["spikes"]]
    qa_rows += [{"timestamp": recs[r["index"]]["timestamp"].replace("T", " "), "pm25": recs[r["index"]]["pm25"],
                 "issue": "multivariate anomaly: " + (", ".join(d["feature"] for d in r["top_deviations"]) or "pattern")}
                for r in an["rows"] if r["is_anomaly"] and r["index"] not in pc.vars["spikes"]]
    tone = {"Good": "good", "Moderate": "neutral"}.get(category(fmean), "bad" if fmean > 55.4 else "warn")
    return {
        "headline": f"{pc.input['station']}: next-24h mean PM2.5 {fmean:.1f} {pc.input['unit']} ({category(fmean)}); action: {decision['outcome'].replace('_', ' ')}",
        "metrics": [
            metric("Last 24 h mean", f"{current:.1f}", hint=category(current)),
            metric("Next 24 h forecast mean", f"{fmean:.1f}", tone, hint=category(fmean)),
            metric("Sensor gaps filled", pc.vars["gaps"], "warn" if pc.vars["gaps"] else "good"),
            metric("Faulty spikes removed", len(pc.vars["spikes"]), "warn" if pc.vars["spikes"] else "good"),
            metric("Backtest MAE", f"{bt['model_mae']:.1f}", "good" if bt["beats_baseline"] else "warn",
                   hint=f"baseline ({bt['baseline']}) {bt['baseline_mae']:.1f}"),
        ],
        "charts": [chart("line", f"PM2.5 ({pc.input['unit']}) — last 72 h and forecast", data, "t",
                         [("pm25", "Observed"), ("forecast", "Forecast"), ("upper", "Upper ~95%"), ("lower", "Lower ~95%"), ("flagged", "Flagged")],
                         reference_lines=[{"y": 35.4, "label": "USG"}, {"y": 55.4, "label": "Unhealthy"}])],
        "tables": [table("Sensor quality issues", [("timestamp", "Time"), ("pm25", "PM2.5"), ("issue", "Issue")], qa_rows)],
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["Bands follow US EPA 2024 PM2.5 breakpoints (configurable). Readings are synthetic.",
                  "Isolated spikes are replaced by the neighbour mean before forecasting so a faulty sample cannot trigger an advisory."],
    }


ADAPTER = DomainAdapter(
    id="environment", name="Environment & Sustainability", icon="Leaf", color="#16a34a",
    tagline="Quality-check air sensors and forecast next-day PM2.5 for timely public advisories",
    description="Fills sensor gaps, removes isolated faulty spikes, detects multivariate anomalies, forecasts PM2.5 with a seasonal model backtested against a naive baseline, and maps the forecast to AQI bands and advisory rules.",
    scenario="Air-quality early warning", impact="Advisories go out a day ahead, and faulty sensors cannot raise false alarms.",
    input_model=Input, sample_file="environment.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("clean", "Clean sensor feed", "data", "clean", build=lambda pc: {"records": pc.input["readings"], "fill_missing": "median"},
             why="Fill gaps, remove duplicates"),
        Step("anomaly", "Sensor anomaly detection", "ml", "anomaly",
             build=lambda pc: {"records": pc.r("clean")["records"], "id_field": "timestamp", "contamination": 0.02,
                               "features": ["pm25", "temperature_c", "humidity_pct", "wind_speed_ms"]}),
        Step("forecast", "PM2.5 forecast", "ml", "forecast", build=_qa, why="Spike-filtered series, daily seasonality, backtested"),
        Step("policy", "Advisory rules", "decision", "evaluate_rules", build=_facts),
        Step("explain", "Public advisory text", "ai", "explain", optional=True,
             build=lambda pc: {"subject": f"Air quality at {pc.input['station']}", "audience": "public", "context": {
                 "outcome": pc.r("policy")["outcome"], "matched": pc.r("policy")["matched"],
                 "forecast_24h_mean_pm25": round(pc.vars["forecast_mean"], 1), "category": category(pc.vars["forecast_mean"])}}),
    ],
)
