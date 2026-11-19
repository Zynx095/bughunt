"""Turn alerts, forecasts and routes into explained, advisory actions for human organisers.

Every recommendation carries: the facts that triggered it, the route evidence (if any), a
confidence taken from the weakest reading involved, and ``requires_human_decision = True``.
``validate_action`` is a hard guard: no software recommendation may close, lock, hold or meter an
emergency exit. Exits can only be the subject of "clear obstruction" / "keep open" actions.
"""
from __future__ import annotations

import math
from typing import Any

from .congestion_detector import SEVERITY_RANK
from .route_optimizer import RouteOptimizer, RouteState
from .venue import Venue

RESTRICTIVE_ACTIONS = {"close", "lock", "hold_entry", "meter_entry", "restrict", "block"}
CAPACITY_ALERTS = {"overcrowded", "near_capacity", "dangerous_density", "forecast_capacity_breach", "rapid_build_up"}
DISCLAIMER = ("Advisory only. CROWDGUARD estimates crowd conditions from imperfect sensors and models; it does not "
              "certify that an event is safe. Organisers and the safety officer make every intervention decision.")


def validate_action(action: dict[str, Any], venue: Venue) -> tuple[bool, str]:
    target = action.get("target")
    if action.get("action_type") in RESTRICTIVE_ACTIONS and target and venue.is_emergency_exit(target):
        return False, "Refused: an emergency exit can never be closed, held or restricted by a software recommendation."
    return True, "permitted (advisory; human decision required)"


def _rec(rid: str, severity: str, action_type: str, target: str, venue: Venue, title: str, detail: str,
         rationale: list[str], confidence: float | None, **extra: Any) -> dict[str, Any]:
    rec = {"id": rid, "severity": severity, "action_type": action_type, "target": target,
           "target_name": venue.name_of(target), "title": title, "detail": detail, "rationale": rationale,
           "confidence": round(confidence, 3) if confidence is not None else None,
           "requires_human_decision": True, "status": "proposed", **extra}
    ok, why = validate_action(rec, venue)
    rec["permitted"], rec["guard"] = ok, why
    return rec


def build_recommendations(venue: Venue, readings: dict[str, dict[str, Any]], alerts: list[dict[str, Any]],
                          forecasts: dict[str, dict[str, Any]], state: RouteState,
                          planner: RouteOptimizer | None = None) -> list[dict[str, Any]]:
    planner = planner or RouteOptimizer(venue)
    th = venue.thresholds
    recs: list[dict[str, Any]] = []
    by_target: dict[str, list[dict[str, Any]]] = {}
    for a in alerts:
        by_target.setdefault(a["target"], []).append(a)

    # 1. Zones over, near, or forecast to exceed capacity: relieve them and slow what feeds them.
    for zid, zalerts in by_target.items():
        cap_alerts = [a for a in zalerts if a["type"] in CAPACITY_ALERTS and a["entity"] == "zone"]
        if not cap_alerts:
            continue
        zone = venue.zones.get(zid)
        r = readings.get(zid) or {}
        fc = forecasts.get(zid) or {}
        sev = max(cap_alerts, key=lambda a: SEVERITY_RANK[a["severity"]])["severity"]
        est = r.get("estimate") or 0
        target = th["target_relief_pct"] / 100.0 * zone.safe_capacity
        projected = max(est, fc.get("predicted_end") or 0) if fc.get("available") else est
        group = int(math.ceil(max(0.0, projected - target) / 50.0) * 50)
        rationale = [a["message"] for a in cap_alerts]
        if fc.get("available"):
            rationale.append(f"Forecast ({fc['method']}): {fc['predicted_end_pct']}% in {fc['horizon']} min "
                             f"(band {fc['lower'][-1]:,}–{fc['upper'][-1]:,} people).")
        if group > 0:
            plan = planner.plan(state, zid, "relieve", group)
            if plan["recommended"]:
                alloc = "; ".join(f"~{a['people']:,} → {a['destination_name']}" for a in plan["allocation"]) or "see route"
                recs.append(_rec(f"relieve:{zid}", sev, "relieve_zone", zid, venue,
                                 f"Relieve {zone.name}: guide ~{group:,} people to safer areas",
                                 f"Target ≤ {th['target_relief_pct']:.0f}% of safe capacity. Allocation: {alloc}.",
                                 rationale + plan["explanation"], r.get("confidence"), route=plan, group_size=group))
            else:
                recs.append(_rec(f"relieve:{zid}", sev, "escalate", zid, venue,
                                 f"No safe relief route from {zone.name}",
                                 "Every alternative destination is full, unverified or unreachable without crossing a crowded zone.",
                                 rationale + plan["explanation"], r.get("confidence"), route=plan, group_size=group))
        # Slow admissions at the public entrances (never at emergency exits).
        if sev == "critical" or any(a["type"] == "forecast_capacity_breach" for a in cap_alerts):
            for gate in venue.entrances():
                rec = _rec(f"meter:{gate['id']}:{zid}", "high", "meter_entry", gate["id"], venue,
                           f"Meter admissions at {gate['name']} and signpost arrivals away from {zone.name}",
                           "Reduce the arrival rate feeding the build-up; keep the gate itself open for anyone leaving.",
                           rationale[:2], r.get("confidence"))
                if rec["permitted"]:
                    recs.append(rec)

    # 2. Blocked exits: clear them, and re-plan egress for zones that relied on them.
    for a in alerts:
        if a["type"] != "exit_blocked":
            continue
        xid = a["target"]
        recs.append(_rec(f"clear:{xid}", "critical", "clear_exit_obstruction", xid, venue,
                         f"Dispatch stewards to clear {venue.name_of(xid)} immediately",
                         "Exit capacity is lost while the obstruction remains. The exit must stay designated open.",
                         [a["message"]], 1.0))
        affected = []
        for zone in venue.zones.zones:
            plan_free = planner.plan(RouteState(state.zones, state.edge_utilisation, set(state.blocked_edges),
                                                set(state.blocked_nodes) - {xid}), zone.id, "egress", 100)
            if plan_free["recommended"] and plan_free["recommended"]["destination"] == xid:
                affected.append(zone.id)
        for zid in affected[:3]:
            est = (readings.get(zid) or {}).get("estimate") or 0
            plan = planner.plan(state, zid, "egress", max(100, int(est)))
            if plan["recommended"]:
                recs.append(_rec(f"egress:{zid}:{xid}", "high", "reroute_egress", zid, venue,
                                 f"Re-route {venue.name_of(zid)} egress to {plan['recommended']['destination_name']}",
                                 f"{venue.name_of(xid)} is unavailable; brief stewards and update signage.",
                                 [a["message"]] + plan["explanation"], (readings.get(zid) or {}).get("confidence"), route=plan))

    # 3. Feed health: unknown is not empty.
    for a in alerts:
        if a["type"] in ("stale_feed", "detection_failure"):
            zid = a["target"]
            recs.append(_rec(f"verify:{zid}", "medium", "verify_feed", zid, venue,
                             f"Restore or verify monitoring for {venue.name_of(zid)}",
                             "Send a steward to observe and report occupancy; do not route people into this zone until verified.",
                             [a["message"]], (readings.get(zid) or {}).get("confidence")))

    # 4. Queues, slow crowds and bottlenecks.
    for a in alerts:
        if a["type"] == "slow_moving_queue":
            recs.append(_rec(f"queue:{a['target']}", "medium", "manage_queue", a["target"], venue,
                             f"Open extra service points or split the queue at {a['target_name']}",
                             "Reduces wait time and stops the queue spilling into circulation routes.", [a["message"]], a.get("confidence")))
        elif a["type"] == "bottleneck":
            recs.append(_rec(f"bneck:{a['target']}", "medium", "steward_bottleneck", a["target"], venue,
                             f"Station stewards at {a['target_name']}",
                             "Keep the corridor moving (consider one-way flow); demand is near its flow capacity.", [a["message"]], None))
        elif a["type"] == "slow_moving_crowd":
            recs.append(_rec(f"slow:{a['target']}", "medium", "monitor", a["target"], venue,
                             f"Watch {a['target_name']} for compression",
                             "Slow walking at moderate density can precede stop-and-go waves.", [a["message"]], a.get("confidence")))

    seen: set[str] = set()
    unique = []
    for rec in sorted(recs, key=lambda x: (-SEVERITY_RANK[x["severity"]], x["id"])):
        if rec["id"] not in seen:
            seen.add(rec["id"])
            unique.append(rec)
    for i, rec in enumerate(unique, 1):
        rec["priority"] = i
    return unique
