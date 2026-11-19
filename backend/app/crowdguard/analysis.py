"""Shared analysis of one moment in time: readings -> forecasts -> alerts -> routes -> recommendations.

Used by the deterministic simulator (every tick) and by live assessment of camera-derived readings,
so both paths produce exactly the same kind of output.
"""
from __future__ import annotations

from typing import Any

from .congestion_detector import Evaluator, default_rules, detect, zone_facts
from .crowd_flow import trend_per_minute
from .crowd_forecaster import forecast_zone
from .route_optimizer import RouteOptimizer, RouteState
from .safety_recommendations import DISCLAIMER, build_recommendations
from .venue import Venue


def zone_forecasts(venue: Venue, history: dict[str, list[float | None]], step_minutes: float = 1.0) -> dict[str, dict[str, Any]]:
    h = int(venue.thresholds["forecast_horizon_min"] / step_minutes)
    return {z.id: forecast_zone(history.get(z.id, []), z.safe_capacity, horizon=max(1, h), step_minutes=step_minutes)
            for z in venue.zones.zones}


def build_facts(venue: Venue, readings: dict[str, dict[str, Any]], pct_history: dict[str, list[float | None]],
                flows: dict[str, dict[str, Any]], forecasts: dict[str, dict[str, Any]],
                edge_flows: list[dict[str, Any]], exit_status: dict[str, str], step_minutes: float = 1.0) -> list[dict[str, Any]]:
    facts = []
    for z in venue.zones.zones:
        r = readings.get(z.id)
        if r is None:
            continue
        growth = trend_per_minute(pct_history.get(z.id, []), step_minutes=step_minutes) if r.get("feed_status") == "ok" else None
        facts.append(zone_facts(z, r, growth_pct_per_min=growth, flow=flows.get(z.id), forecast=forecasts.get(z.id)))
    for x in venue.exits():
        facts.append({"entity": "exit", "exit_id": x["id"], "name": x["name"], "status": exit_status.get(x["id"], "open"),
                      "emergency_exit": bool(x.get("emergency_exit"))})
    for e in edge_flows:
        if e.get("capacity_ppm"):
            facts.append({"entity": "edge", "edge_id": e["id"], "label": f"{venue.name_of(e['from'])} → {venue.name_of(e['to'])}",
                          "utilisation": e.get("utilisation", 0.0), "flow_ppm": e.get("flow_ppm"), "capacity_ppm": e["capacity_ppm"]})
    return facts


def route_state(venue: Venue, readings: dict[str, dict[str, Any]], edge_flows: list[dict[str, Any]],
                exit_status: dict[str, str], extra_blocked_edges: set[str] | None = None) -> RouteState:
    util: dict[str, float] = {}
    for e in edge_flows:
        util[e["id"]] = max(util.get(e["id"], 0.0), e.get("utilisation", 0.0))
    blocked_nodes = {x for x, s in exit_status.items() if s == "blocked"}
    return RouteState(zones=readings, edge_utilisation=util, blocked_edges=set(extra_blocked_edges or set()),
                      blocked_nodes=blocked_nodes)


def summarise(venue: Venue, readings: dict[str, dict[str, Any]], alerts: list[dict[str, Any]],
              exit_status: dict[str, str]) -> dict[str, Any]:
    known = [r for r in readings.values() if r.get("estimate") is not None]
    total = sum(r["estimate"] for r in known)
    lo = sum(r["lower"] for r in known)
    hi = sum(r["upper"] for r in known)
    unknown = [zid for zid, r in readings.items() if r.get("band") == "unknown" or r.get("feed_status") != "ok"]
    exits = venue.exits()
    return {
        "estimated_attendance": total, "attendance_lower": lo, "attendance_upper": hi,
        "zones_total": len(venue.zones.zones), "zones_without_live_data": len(unknown), "zones_without_live_data_ids": unknown,
        "zones_high_or_critical": sum(1 for r in readings.values() if r.get("band") in ("high", "critical")),
        "alerts_critical": sum(1 for a in alerts if a["severity"] == "critical"),
        "alerts_high": sum(1 for a in alerts if a["severity"] == "high"),
        "alerts_total": len(alerts),
        "exits_total": len(exits), "exits_available": sum(1 for x in exits if exit_status.get(x["id"], "open") == "open"),
        "coverage_note": ("Attendance excludes zones with no data" if any(r.get("estimate") is None for r in readings.values()) else None),
    }


def analyse_snapshot(venue: Venue, *, t: float, readings: dict[str, dict[str, Any]], history: dict[str, list[float | None]],
                     pct_history: dict[str, list[float | None]], flows: dict[str, dict[str, Any]],
                     edge_flows: list[dict[str, Any]], exit_status: dict[str, str], evaluator: Evaluator,
                     step_minutes: float = 1.0, alerts: list[dict[str, Any]] | None = None,
                     forecasts: dict[str, dict[str, Any]] | None = None, planner: RouteOptimizer | None = None) -> dict[str, Any]:
    forecasts = forecasts if forecasts is not None else zone_forecasts(venue, history, step_minutes)
    if alerts is None:
        facts = build_facts(venue, readings, pct_history, flows, forecasts, edge_flows, exit_status, step_minutes)
        alerts = detect(facts, default_rules(venue.thresholds), evaluator)
    state = route_state(venue, readings, edge_flows, exit_status)
    planner = planner or RouteOptimizer(venue)
    recs = build_recommendations(venue, readings, alerts, forecasts, state, planner)
    return {"t": t, "readings": readings, "forecasts": forecasts, "flows": flows, "edge_flows": edge_flows,
            "exit_status": exit_status, "alerts": alerts, "recommendations": recs,
            "summary": summarise(venue, readings, alerts, exit_status), "disclaimer": DISCLAIMER}
