"""Overcrowding, build-up, queue, bottleneck and feed-health alerts from configurable rules.

Rules are plain data in the decision engine's JSON DSL, generated from the venue thresholds, so
organisers can change them without code. Evaluation is delegated to the decision engine
(``decision.evaluate_rules``) through an injected evaluator; nothing here re-implements it.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

Evaluator = Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]]
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def default_rules(th: dict[str, float]) -> list[dict[str, Any]]:
    zone = {"field": "entity", "op": "eq", "value": "zone"}
    return [
        {"id": "zone-overcrowded", "severity": "critical", "outcome": "overcrowded",
         "description": f"Estimated occupancy at or above {th['critical_pct']:.0f}% of safe capacity",
         "when": {"all": [zone, {"field": "occupancy_pct", "op": "gte", "value": th["critical_pct"]}]}},
        {"id": "zone-near-capacity", "severity": "high", "outcome": "near_capacity",
         "description": f"Estimated occupancy at or above {th['high_pct']:.0f}% of safe capacity",
         "when": {"all": [zone, {"field": "occupancy_pct", "op": "gte", "value": th["high_pct"]},
                          {"field": "occupancy_pct", "op": "lt", "value": th["critical_pct"]}]}},
        {"id": "zone-density-critical", "severity": "critical", "outcome": "dangerous_density",
         "description": f"Density at or above {th['density_critical']} persons/m²",
         "when": {"all": [zone, {"field": "density", "op": "gte", "value": th["density_critical"]}]}},
        {"id": "zone-rapid-increase", "severity": "high", "outcome": "rapid_build_up",
         "description": f"Occupancy rising ≥ {th['growth_pct_per_min']}% of capacity per minute",
         "when": {"all": [zone, {"field": "growth_pct_per_min", "op": "gte", "value": th["growth_pct_per_min"]},
                          {"field": "occupancy_pct", "op": "gte", "value": th.get("growth_min_occupancy_pct", 50)}]}},
        {"id": "zone-forecast-breach", "severity": "high", "outcome": "forecast_capacity_breach",
         "description": f"Forecast reaches safe capacity within {th['forecast_horizon_min']:.0f} min",
         "when": {"all": [zone, {"field": "forecast_minutes_to_capacity", "op": "lte", "value": th["forecast_horizon_min"]},
                          {"field": "occupancy_pct", "op": "lt", "value": th["critical_pct"]}]}},
        {"id": "zone-slow-queue", "severity": "medium", "outcome": "slow_moving_queue",
         "description": f"Queue wait ≥ {th['queue_wait_min']:.0f} min (Little's law: occupancy ÷ service rate)",
         "when": {"all": [zone, {"field": "is_queue", "op": "eq", "value": True},
                          {"field": "queue_wait_min", "op": "gte", "value": th["queue_wait_min"]}]}},
        {"id": "zone-slow-crowd", "severity": "medium", "outcome": "slow_moving_crowd",
         "description": f"Walking speed below {th['slow_speed_mps']} m/s at density ≥ {th['slow_density']} persons/m²",
         "when": {"all": [zone, {"field": "is_queue", "op": "eq", "value": False},
                          {"field": "mean_speed", "op": "lt", "value": th["slow_speed_mps"]},
                          {"field": "density", "op": "gte", "value": th["slow_density"]}]}},
        {"id": "zone-stale-feed", "severity": "medium", "outcome": "stale_feed",
         "description": "Camera feed stale or missing: occupancy unknown, NOT zero",
         "when": {"all": [zone, {"field": "feed_status", "op": "in", "value": ["stale", "missing"]}]}},
        {"id": "zone-detector-failure", "severity": "medium", "outcome": "detection_failure",
         "description": "Frames received but person detection failed",
         "when": {"all": [zone, {"field": "feed_status", "op": "eq", "value": "detector_error"}]}},
        {"id": "zone-low-confidence", "severity": "low", "outcome": "low_confidence",
         "description": f"Estimate confidence below {th['min_confidence']}",
         "when": {"all": [zone, {"field": "feed_status", "op": "eq", "value": "ok"},
                          {"field": "confidence", "op": "lt", "value": th["min_confidence"]}]}},
        {"id": "exit-blocked", "severity": "critical", "outcome": "exit_blocked",
         "description": "Exit reported blocked or obstructed",
         "when": {"all": [{"field": "entity", "op": "eq", "value": "exit"}, {"field": "status", "op": "eq", "value": "blocked"}]}},
        {"id": "edge-bottleneck", "severity": "medium", "outcome": "bottleneck",
         "description": f"Corridor demand ≥ {th['bottleneck_utilisation']:.0%} of its flow capacity",
         "when": {"all": [{"field": "entity", "op": "eq", "value": "edge"},
                          {"field": "utilisation", "op": "gte", "value": th["bottleneck_utilisation"]}]}},
    ]


def zone_facts(zone, reading: dict[str, Any], *, growth_pct_per_min: float | None, flow: dict[str, Any] | None,
               forecast: dict[str, Any] | None) -> dict[str, Any]:
    est = reading.get("estimate")
    is_queue = zone.kind == "queue"
    wait = None
    if is_queue and zone.service_rate_ppm and est is not None:
        wait = round(est / zone.service_rate_ppm, 1)
    return {
        "entity": "zone", "zone_id": zone.id, "zone_name": zone.name, "zone_kind": zone.kind, "is_queue": is_queue,
        "estimate": est, "capacity": zone.safe_capacity, "occupancy_pct": reading.get("occupancy_pct"),
        "upper_pct": reading.get("upper_pct"), "density": reading.get("density_ppm2"),
        "growth_pct_per_min": round(growth_pct_per_min, 2) if growth_pct_per_min is not None else None,
        "feed_status": reading.get("feed_status"), "age_s": reading.get("age_s"), "confidence": reading.get("confidence"),
        "mean_speed": (flow or {}).get("mean_speed"), "stationary_fraction": (flow or {}).get("stationary_fraction"),
        "queue_wait_min": wait,
        "forecast_peak_pct": (forecast or {}).get("peak_pct") if (forecast or {}).get("available") else None,
        "forecast_minutes_to_capacity": (forecast or {}).get("minutes_to_capacity") if (forecast or {}).get("available") else None,
        "carried_forward": reading.get("carried_forward"),
    }


def _message(rule_id: str, f: dict[str, Any]) -> str:
    name = f.get("zone_name") or f.get("name") or f.get("edge_id")
    pct = f.get("occupancy_pct")
    if rule_id == "zone-overcrowded":
        return f"{name} at {pct}% of safe capacity (≈{f['estimate']:,} of {f['capacity']:,})"
    if rule_id == "zone-near-capacity":
        return f"{name} near capacity: {pct}% (≈{f['estimate']:,} of {f['capacity']:,})"
    if rule_id == "zone-density-critical":
        return f"{name} density {f['density']} persons/m²"
    if rule_id == "zone-rapid-increase":
        return f"{name} filling fast: +{f['growth_pct_per_min']}% of capacity per minute (now {pct}%)"
    if rule_id == "zone-forecast-breach":
        return f"{name} forecast to reach safe capacity in ~{f['forecast_minutes_to_capacity']:.0f} min (now {pct}%)"
    if rule_id == "zone-slow-queue":
        return f"{name}: slow-moving queue, estimated wait {f['queue_wait_min']} min"
    if rule_id == "zone-slow-crowd":
        return f"{name}: crowd moving slowly ({f['mean_speed']} m/s at {f['density']} persons/m²)"
    if rule_id == "zone-stale-feed":
        age = f.get("age_s")
        return f"{name}: camera feed {f['feed_status']}" + (f" ({age:.0f} s since last reading)" if age else "") + " — occupancy unknown"
    if rule_id == "zone-detector-failure":
        return f"{name}: person detection failed — occupancy unknown"
    if rule_id == "zone-low-confidence":
        return f"{name}: low-confidence estimate ({f['confidence']})"
    if rule_id == "exit-blocked":
        return f"{f['name']} blocked" + (" (EMERGENCY EXIT)" if f.get("emergency_exit") else "")
    if rule_id == "edge-bottleneck":
        return f"Bottleneck on {f.get('label', f.get('edge_id'))}: {f['utilisation']:.0%} of flow capacity"
    return f"{name}: {rule_id}"


def local_evaluator() -> Evaluator:
    """Evaluate with a private DecisionEngine instance (the same implementation, no registry/audit).
    The crowd engine injects a registry-backed evaluator instead."""
    from app.core.contracts import ExecutionContext  # noqa: PLC0415
    from app.engines.decision.engine import DecisionEngine  # noqa: PLC0415

    eng = DecisionEngine(store=None)

    def evaluate(rules: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resp = eng.execute("evaluate_rules", {"rules": rules, "facts": facts, "default_outcome": "ok"},
                           ExecutionContext(actor="crowdguard", role="analyst", actor_type="system"))
        if not resp.success:
            raise RuntimeError(f"rule evaluation failed: {resp.error}")
        return resp.result["results"]

    return evaluate


def detect(facts: Iterable[dict[str, Any]], rules: list[dict[str, Any]], evaluator: Evaluator) -> list[dict[str, Any]]:
    """Return one alert per matched rule per fact, most severe first."""
    facts = list(facts)
    if not facts:
        return []
    results = evaluator(rules, facts)
    alerts = []
    for f, r in zip(facts, results):
        for m in r.get("matched", []):
            target = f.get("zone_id") or f.get("exit_id") or f.get("edge_id")
            alerts.append({"id": f"{m['id']}:{target}", "rule": m["id"], "severity": m["severity"], "type": m["outcome"],
                           "entity": f["entity"], "target": target, "target_name": f.get("zone_name") or f.get("name") or f.get("label"),
                           "message": _message(m["id"], f), "rule_description": m["description"],
                           "confidence": f.get("confidence"), "facts": {k: v for k, v in f.items() if v is not None}})
    alerts.sort(key=lambda a: (-SEVERITY_RANK[a["severity"]], a["id"]))
    return alerts
