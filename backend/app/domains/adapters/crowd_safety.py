"""Public safety: CROWDGUARD crowd safety monitoring at public events (dedicated adapter).

A pipeline over the engines for one decision point of the synthetic event: zone snapshot (crowd) →
backtested forecast for the busiest zone (ml) → explainable risk score per zone (decision) →
safety-weighted relief route (crowd) → organiser briefing (ai) → evidence hash (crypto).
The interactive command centre uses the same `crowd` engine operations directly.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table, tone_for_band

BAND_TONE = {"critical": "critical", "high": "high", "elevated": "medium", "normal": "low", "unknown": None}


class Input(BaseModel):
    decision_tick: int = Field(38, ge=8, le=65, description="Minute of the synthetic event to assess (18:00 + tick)")
    seed: int = Field(2026, ge=0)
    intervention: bool = True
    exit_blockage: bool = True
    feed_outage: bool = True


def _snapshot(pc: PipelineContext):
    i = pc.input
    return {"tick": i["decision_tick"], "seed": i["seed"], "intervention": i["intervention"],
            "exit_blockage": i["exit_blockage"], "feed_outage": i["feed_outage"]}


def _frame(pc: PipelineContext) -> dict:
    return pc.r("snapshot")["frame"]


def _hot_zone(pc: PipelineContext) -> str:
    readings = _frame(pc)["readings"]
    return max(readings, key=lambda z: readings[z].get("occupancy_pct") or -1)


def _forecast(pc: PipelineContext):
    hist = [v for v in pc.r("snapshot")["history"][_hot_zone(pc)] if v is not None]
    return {"values": hist, "horizon": 15} if len(hist) >= 8 else None


def _risk(pc: PipelineContext):
    f = _frame(pc)
    items = []
    for zid, r in f["readings"].items():
        fc = f["forecasts"].get(zid) or {}
        items.append({"id": zid, "factors": [
            {"name": "occupancy % of safe capacity", "value": r.get("occupancy_pct") or 0, "min": 40, "max": 110, "weight": 3},
            {"name": "density (persons/m²)", "value": r.get("density_ppm2") or 0, "min": 0.5, "max": 4.5, "weight": 2},
            {"name": "forecast peak %", "value": fc.get("peak_pct") or 0, "min": 50, "max": 110, "weight": 2},
            {"name": "data confidence", "value": r.get("confidence") or 0, "min": 0, "max": 1, "weight": 1, "invert": True},
        ]})
    return {"items": items, "thresholds": {"medium": 35, "high": 60, "critical": 80}}


def _route(pc: PipelineContext):
    f = _frame(pc)
    hot = _hot_zone(pc)
    r = f["readings"][hot]
    cap = r["safe_capacity"]
    group = max(100, int((max(r.get("estimate") or 0, (f["forecasts"][hot] or {}).get("predicted_end") or 0) - 0.8 * cap) // 50 * 50))
    return {"source": hot, "purpose": "relieve", "group_size": group, "tick": f["tick"]}


def _explain(pc: PipelineContext):
    return {"tick": _frame(pc)["tick"], "audience": "executive"}


def _seal(pc: PipelineContext):
    import json  # noqa: PLC0415

    f = _frame(pc)
    evidence = {"clock": f["clock"], "readings": {z: {k: r.get(k) for k in ("estimate", "lower", "upper", "occupancy_pct", "band", "feed_status")}
                                                  for z, r in f["readings"].items()},
                "alerts": [a["id"] for a in f["alerts"]], "exit_status": f["exit_status"]}
    return {"text": json.dumps(evidence, sort_keys=True, separators=(",", ":"))}


def present(pc: PipelineContext) -> dict:
    f = _frame(pc)
    readings = f["readings"]
    hot = _hot_zone(pc)
    risk = {it["id"]: it for it in pc.r("risk")["items"]}
    plan = pc.r("route") or {}
    rec = plan.get("recommended")
    ml = pc.r("forecast")
    s = f["summary"]
    rows = []
    for zid, r in sorted(readings.items(), key=lambda kv: -(kv[1].get("occupancy_pct") or -1)):
        fc = f["forecasts"].get(zid) or {}
        rows.append({"zone": zid, "estimate": r.get("estimate"), "interval": f"{r.get('lower')}–{r.get('upper')}" if r.get("estimate") is not None else "unknown",
                     "capacity": r["safe_capacity"], "occupancy_pct": r.get("occupancy_pct"), "band": BAND_TONE.get(r.get("band")) or r.get("band"),
                     "zone_band": r.get("band"), "feed": r.get("feed_status"), "confidence": r.get("confidence"),
                     "forecast_peak_pct": fc.get("peak_pct"), "risk_score": risk.get(zid, {}).get("score")})
    hist = pc.r("snapshot")["history"][hot]
    line = [{"minute": i, "estimate": v} for i, v in enumerate(hist)]
    if ml:
        n = len(hist)
        line += [{"minute": n - 1 + k + 1, "forecast": round(v), "lower": round(lo), "upper": round(hi)}
                 for k, (v, lo, hi) in enumerate(zip(ml["forecast"], ml["lower"], ml["upper"]))]
    cap = readings[hot]["safe_capacity"]
    return {
        "headline": f"{f['clock']} (synthetic): {s['zones_high_or_critical']} zone(s) high/critical, {s['alerts_total']} alerts; "
                    + (f"relief route {' → '.join(rec['names'])}" if rec else "no safe relief route"),
        "metrics": [
            metric("Estimated attendance", f"{s['estimated_attendance']:,}", hint=f"interval {s['attendance_lower']:,}–{s['attendance_upper']:,}"),
            metric(f"{readings[hot].get('occupancy_pct')}% {hot.replace('_', ' ')}", readings[hot].get("band"),
                   "bad" if readings[hot].get("band") in ("high", "critical") else "warn" if readings[hot].get("band") == "elevated" else "good"),
            metric("Critical / high alerts", f"{s['alerts_critical']} / {s['alerts_high']}", "bad" if s["alerts_critical"] else "warn" if s["alerts_high"] else "good"),
            metric("Exits available", f"{s['exits_available']} / {s['exits_total']}", "bad" if s["exits_available"] < s["exits_total"] else "good"),
            metric("ML forecast backtest", f"MAE {ml['backtest']['model_mae']:.0f} vs {ml['backtest']['baseline_mae']:.0f}" if ml else "n/a",
                   "good" if ml and ml["backtest"]["beats_baseline"] else "warn", hint=f"model {ml['selected_model']}, baseline {ml['backtest']['baseline']}" if ml else None),
        ],
        "charts": [
            chart("bar", "Occupancy by zone (% of safe capacity)", [{"zone": r["zone"], "occupancy_pct": r["occupancy_pct"] or 0, "band": r["band"] or "unknown"} for r in rows],
                  "zone", [("occupancy_pct", "Occupancy %")], color_by="band", layout="vertical", reference_lines=[{"y": 100, "label": "safe capacity"}]),
            chart("line", f"{hot.replace('_', ' ').title()} estimate and ML-engine forecast", line, "minute",
                  [("estimate", "Estimate"), ("forecast", "Forecast"), ("lower", "Lower 95%"), ("upper", "Upper 95%")],
                  reference_lines=[{"y": cap, "label": "safe capacity"}]),
        ],
        "tables": [
            table("Zones (estimates, not ground truth)", [("zone", "Zone"), ("estimate", "Estimate"), ("interval", "Interval"), ("capacity", "Safe cap."),
                  ("occupancy_pct", "%"), ("zone_band", "Band"), ("feed", "Feed"), ("confidence", "Conf."), ("forecast_peak_pct", "Fcst peak %"),
                  ("risk_score", "Risk")], rows),
            table("Active alerts", [("severity", "Severity"), ("message", "Alert"), ("rule", "Rule")],
                  [{"severity": a["severity"], "message": a["message"], "rule": a["rule"]} for a in f["alerts"]]),
            table("Recommendations (advisory; human decision required)", [("priority", "#"), ("severity", "Severity"), ("title", "Action"), ("detail", "Detail")],
                  [{k: r[k] for k in ("priority", "severity", "title", "detail")} for r in f["recommendations"]]),
        ],
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["All values are SYNTHETIC (deterministic simulation).",
                  "Route suggestions never enter overcrowded zones and are never presented as safe just because they are short.",
                  "Advisory only: organisers make the intervention decision; no software action can close an emergency exit.",
                  f"Evidence hash (SHA-256): {(pc.r('seal') or {}).get('digest', 'n/a')}"],
    }


ADAPTER = DomainAdapter(
    id="crowd_safety", name="CROWDGUARD · Crowd Safety", icon="Users", color="#d9480f",
    tagline="Estimate zone occupancy, flag dangerous build-up early and suggest safer crowd movement",
    description="Assesses a moment of a synthetic multi-zone festival: occupancy estimates with uncertainty, configurable alert rules "
                "(decision engine), a backtested forecast (ML engine), explainable per-zone risk, a safety-weighted relief route "
                "(NetworkX) and an organiser briefing, sealed with an evidence hash.",
    scenario="Crowd safety monitoring at public events", impact="Organisers see a capacity breach coming minutes ahead, with a vetted alternative route.",
    input_model=Input, sample_file="crowd_safety.json", present=present,
    sections=["overview", "workspace", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("snapshot", "Zone snapshot (synthetic)", "crowd", "simulate", build=_snapshot, why="Occupancy, alerts, forecasts at the decision tick"),
        Step("forecast", "Backtested forecast (busiest zone)", "ml", "forecast", build=_forecast, optional=True, why="Model selection vs naive baseline"),
        Step("risk", "Per-zone risk score", "decision", "risk_score", build=_risk, why="Explainable weighted factors"),
        Step("route", "Safety-weighted relief route", "crowd", "route", build=_route, why="Avoids overcrowded zones and blocked exits"),
        Step("explain", "Organiser briefing", "crowd", "explain", build=_explain, optional=True, why="AI engine, local fallback"),
        Step("seal", "Evidence hash", "crypto", "hash", build=_seal, why="Tamper-evident snapshot"),
    ],
)
