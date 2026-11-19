"""Deterministic synthetic event: a festival evening where the Main Stage fills dangerously.

Everything produced here is SYNTHETIC and labelled as such. The model is macroscopic: zones are
reservoirs, people move between them along corridor paths each minute, and corridor throughput
is capped by width × planning flow rate scaled by walking speed at the source density. A
synthetic camera per zone "sees" the hidden true occupancy with density-dependent occlusion and
small seeded noise, and the normal estimation pipeline turns that into estimates. The same seed
always gives byte-identical output.

Storyline (default parameters):
  18:00 gates open · ~18:25 Main Stage starts filling fast · forecast flags a capacity breach ·
  near-capacity alert · 18:45 East Emergency Exit E1 obstructed · 18:48 organisers act on the
  recommendation (simulated decision) · 18:54–18:58 Food Court camera drops out (unknown, not empty) ·
  19:00 headline act · 19:02 E1 cleared · Main Stage recovers below 85%.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import networkx as nx
import numpy as np

from .analysis import analyse_snapshot, build_facts, zone_forecasts
from .congestion_detector import Evaluator, default_rules, detect
from .crowd_flow import walking_speed, zone_net_flow
from .crowd_forecaster import rolling_backtest
from .density_estimator import Observation, assess_reading, expected_recall
from .route_optimizer import RouteOptimizer
from .venue import Venue


@dataclass(frozen=True)
class ScenarioConfig:
    seed: int = 2026
    ticks: int = 66
    intervention: bool = True
    intervention_tick: int = 40
    relief_minutes: int = 18
    exit_blockage: bool = True
    blockage_tick: int = 44
    blockage_cleared_tick: int = 58
    blocked_exit: str = "exit_east"
    feed_outage: bool = True
    outage_zone: str = "food_court"
    outage_start: int = 49
    outage_end: int = 53
    detector_glitch: bool = True
    glitch_zone: str = "bar_queue"
    glitch_ticks: tuple[int, ...] = (26, 27)
    sensor_noise: float = 0.02


INITIAL = {"north_plaza": 250, "main_stage": 1400, "west_concourse": 300, "east_concourse": 250, "food_court": 900,
           "bar_queue": 80, "second_stage": 800, "south_plaza": 120}


def arrivals(t: int, metered: bool) -> dict[str, float]:
    """People per minute arriving through each gate (smooth, deterministic schedule)."""
    if t < 10:
        north, south = 110 + 6 * t, 45 + 2 * t
    elif t < 40:
        north, south = 155.0, 58.0
    elif t < 60:
        north, south = 140.0, 50.0
    else:
        north, south = max(30.0, 150 - 8 * (t - 60)), max(15.0, 55 - 3 * (t - 60))
    if metered:  # admissions metered at the public gates (never at an emergency exit; gates stay open for leaving)
        north, south = north * 0.6, south * 0.7
    return {"gate_north": north, "gate_south": south}


def routing(t: int, relief: bool, redirected: bool) -> dict[str, tuple[float, dict[str, float]]]:
    """Per-zone (fraction leaving per minute, {next zone: share}). Hype builds before the 19:00 headliner."""
    hype = 0.0 if t < 15 else min(1.0, (t - 15) / 18)
    table = {
        "north_plaza": (0.8, {"main_stage": 0.5 + 0.2 * hype, "west_concourse": 0.25 - 0.1 * hype, "east_concourse": 0.25 - 0.1 * hype}),
        "south_plaza": (0.8, {"main_stage": 0.45 + 0.2 * hype, "food_court": 0.25 - 0.1 * hype, "second_stage": 0.25 - 0.12 * hype,
                              "bar_queue": 0.05 - 0.03 * hype}),
        "west_concourse": (0.5, {"food_court": 0.55 - 0.25 * hype, "main_stage": 0.45 + 0.25 * hype}),
        "east_concourse": (0.5, {"second_stage": 0.55 - 0.25 * hype, "main_stage": 0.45 + 0.25 * hype}),
        "main_stage": (0.04 - 0.025 * hype, {"food_court": 0.45, "bar_queue": 0.15, "second_stage": 0.2, "west_concourse": 0.1, "east_concourse": 0.1}),
        "food_court": (0.09, {"main_stage": 0.3 + 0.25 * hype, "bar_queue": 0.2 - 0.08 * hype, "second_stage": 0.25 - 0.12 * hype,
                              "west_concourse": 0.25 - 0.15 * hype}),
        "bar_queue": (-1.0, {"main_stage": 0.5 + 0.3 * hype, "food_court": 0.5 - 0.3 * hype}),  # served at the service rate
        "second_stage": (0.04 + 0.03 * hype, {"main_stage": 0.5 + 0.3 * hype, "food_court": 0.3 - 0.2 * hype, "east_concourse": 0.2 - 0.1 * hype}),
    }
    if redirected:  # arrivals signposted away from the Main Stage; one-in-one-out at the arena
        table.update({
            "north_plaza": (0.8, {"main_stage": 0.2, "west_concourse": 0.42, "east_concourse": 0.38}),
            "south_plaza": (0.8, {"main_stage": 0.15, "food_court": 0.4, "second_stage": 0.37, "bar_queue": 0.08}),
            "west_concourse": (0.5, {"food_court": 0.75, "main_stage": 0.25}),
            "east_concourse": (0.5, {"second_stage": 0.65, "main_stage": 0.35}),
            "food_court": (0.1, {"main_stage": 0.2, "bar_queue": 0.12, "second_stage": 0.23, "west_concourse": 0.45}),
            "bar_queue": (-1.0, {"main_stage": 0.4, "food_court": 0.6}),
            "second_stage": (0.035, {"main_stage": 0.2, "food_court": 0.2, "east_concourse": 0.6}),
            "main_stage": (0.03, {"food_court": 0.35, "bar_queue": 0.1, "second_stage": 0.4, "west_concourse": 0.15}),
        })
    if relief:  # stewards guide part of the Main Stage audience along the recommended relief routes
        table["main_stage"] = (0.045, {"second_stage": 0.6, "food_court": 0.32, "bar_queue": 0.08})
    return table


class EventSimulator:
    def __init__(self, venue: Venue, cfg: ScenarioConfig | None = None) -> None:
        self.venue = venue
        self.cfg = cfg or ScenarioConfig()
        g = venue.graph
        self.paths: dict[tuple[str, str], list[str]] = {}
        zones = venue.zones.ids()
        for a in zones + [n["id"] for n in venue.entrances()]:
            for b in zones:
                if a != b:
                    self.paths[(a, b)] = nx.shortest_path(g, a, b, weight="length_m")

    def _edge_id(self, a: str, b: str) -> str:
        return self.venue.graph.edges[a, b]["id"]

    def run_truth(self) -> list[dict[str, Any]]:
        """Hidden ground-truth trajectory (synthetic)."""
        cfg, venue = self.cfg, self.venue
        occ = {z: float(v) for z, v in INITIAL.items()}
        out = []
        for t in range(cfg.ticks):
            active = cfg.intervention and t >= cfg.intervention_tick
            relief = active and t < cfg.intervention_tick + cfg.relief_minutes
            transfers: list[tuple[str, str, float]] = []
            for gate, rate in arrivals(t, active).items():
                plaza = "north_plaza" if gate == "gate_north" else "south_plaza"
                transfers.append((gate, plaza, rate))
            table = routing(t, relief, active)
            for zid, (leave, shares) in table.items():
                zone = venue.zones.get(zid)
                if leave < 0:
                    moving = min(occ[zid], zone.service_rate_ppm or 30.0)
                else:
                    moving = occ[zid] * leave
                total_share = sum(shares.values()) or 1.0
                for dest, s in shares.items():
                    if s > 0:
                        transfers.append((zid, dest, moving * s / total_share))
            # Corridor capacity: scale transfers sharing an over-capacity directed edge.
            edge_load: dict[tuple[str, str], float] = {}
            routed = []
            for a, b, f in transfers:
                path = [a, b] if venue.graph.has_edge(a, b) else self.paths[(a, b)]
                hops = list(zip(path, path[1:]))
                routed.append((a, b, f, hops))
                for h in hops:
                    edge_load[h] = edge_load.get(h, 0.0) + f
            dens = {z: occ[z] / venue.zones.get(z).area_m2 for z in occ}
            cap_dir: dict[tuple[str, str], float] = {}
            for (u, v) in edge_load:
                e = venue.graph.edges[u, v]
                src_d = dens.get(u, 0.5)
                speed_factor = (walking_speed(src_d) or 1.34) / 1.34
                cap_dir[(u, v)] = e["capacity_ppm"] * max(0.35, speed_factor)
            scale = {h: min(1.0, cap_dir[h] / load) if load > 0 else 1.0 for h, load in edge_load.items()}
            flows_dir: dict[tuple[str, str], float] = {}
            for a, b, f, hops in routed:
                s = min(scale[h] for h in hops)
                moved = f * s
                if a in occ:
                    occ[a] -= moved
                occ[b] += moved
                for h in hops:
                    flows_dir[h] = flows_dir.get(h, 0.0) + moved
            for z in occ:
                occ[z] = max(0.0, occ[z])
            edge_flows = []
            for (u, v), f in sorted(flows_dir.items()):
                e = venue.graph.edges[u, v]
                edge_flows.append({"id": e["id"], "from": u, "to": v, "flow_ppm": round(f, 1),
                                   "capacity_ppm": e["capacity_ppm"], "utilisation": round(edge_load[(u, v)] / max(cap_dir[(u, v)], 1e-6), 3),
                                   "throughput_utilisation": round(f / e["capacity_ppm"], 3)})
            out.append({"t": t, "truth": {z: int(round(v)) for z, v in occ.items()}, "edge_flows": edge_flows,
                        "arrivals_ppm": {k: round(v, 1) for k, v in arrivals(t, active).items()}, "intervention_active": active})
        return out

    def run(self, evaluator: Evaluator) -> dict[str, Any]:
        cfg, venue = self.cfg, self.venue
        rng = np.random.default_rng(cfg.seed)
        truth = self.run_truth()
        step_min = venue.cfg.get("tick_seconds", 60) / 60.0
        zones = venue.zones.zones
        pos = venue.pos()
        history: dict[str, list[float | None]] = {z.id: [] for z in zones}
        pct_history: dict[str, list[float | None]] = {z.id: [] for z in zones}
        prev: dict[str, dict[str, Any]] = {}
        frames_pre = []
        all_facts: list[dict[str, Any]] = []
        spans = []
        for row in truth:
            t = row["t"]
            secs = t * 60.0
            exit_status = {x["id"]: "open" for x in venue.exits()}
            if cfg.exit_blockage and cfg.blockage_tick <= t < cfg.blockage_cleared_tick:
                exit_status[cfg.blocked_exit] = "blocked"
            readings: dict[str, dict[str, Any]] = {}
            flows: dict[str, dict[str, Any]] = {}
            for z in zones:
                true_n = row["truth"][z.id]
                dens = true_n / z.area_m2
                noise = float(rng.normal(0.0, cfg.sensor_noise))  # drawn every tick so outages don't shift the stream
                status = "ok"
                if cfg.feed_outage and z.id == cfg.outage_zone and cfg.outage_start <= t <= cfg.outage_end:
                    status = "stale"
                if cfg.detector_glitch and z.id == cfg.glitch_zone and t in cfg.glitch_ticks:
                    status = "detector_error"
                observed = int(round(true_n * expected_recall(dens) * (1 + noise))) if status == "ok" else None
                obs = Observation(zone_id=z.id, t=secs, feed_status=status, observed_count=observed,
                                  detector_confidence=0.88 if status == "ok" else None, tracking_stability=0.9,
                                  source="simulation", value_kind="synthetic", synthetic_truth=true_n)
                r = assess_reading(z, obs, prev.get(z.id), venue.thresholds)
                readings[z.id] = r
                prev[z.id] = r
                history[z.id].append(r["estimate"] if not r.get("carried_forward") else None)
                pct_history[z.id].append(r["occupancy_pct"] if r["feed_status"] == "ok" else None)
                if z.kind == "queue":
                    speed = 0.2 + 0.35 * float(np.exp(-true_n / 250.0))
                else:
                    speed = walking_speed(dens) or 1.34
                    speed *= 0.6 if z.kind == "stage" else 1.0  # audiences mill rather than walk
                net = zone_net_flow(z.id, pos, row["edge_flows"])
                flows[z.id] = {"mean_speed": round(speed, 3) if status == "ok" else None, "unit": "m/s",
                               "stationary_fraction": round(min(1.0, max(0.0, 1 - speed / 1.34)), 3) if status == "ok" else None,
                               **net}
            hist_copy = {k: list(v) for k, v in history.items()}
            forecasts = zone_forecasts(venue, hist_copy, step_min)
            facts = build_facts(venue, readings, pct_history, flows, forecasts, row["edge_flows"], exit_status, step_min)
            spans.append((len(all_facts), len(all_facts) + len(facts)))
            all_facts.extend(facts)
            frames_pre.append((row, readings, flows, forecasts, exit_status, hist_copy, {k: list(v) for k, v in pct_history.items()}))

        rules = default_rules(venue.thresholds)
        all_alerts_flat = detect_batch(all_facts, rules, evaluator, spans)
        planner = RouteOptimizer(venue)
        frames = []
        for i, (row, readings, flows, forecasts, exit_status, hist, phist) in enumerate(frames_pre):
            snap = analyse_snapshot(venue, t=row["t"] * 60.0, readings=readings, history=hist, pct_history=phist,
                                    flows=flows, edge_flows=row["edge_flows"], exit_status=exit_status,
                                    evaluator=evaluator, step_minutes=step_min, alerts=all_alerts_flat[i],
                                    forecasts=forecasts, planner=planner)
            snap.update(tick=row["t"], clock=clock(venue, row["t"]), arrivals_ppm=row["arrivals_ppm"],
                        intervention_active=row["intervention_active"], events=[e for e in story_events(cfg) if e["tick"] == row["t"]])
            frames.append(compact_frame(snap))
        incidents = incident_lifecycle(cfg, frames, venue)
        for f in frames:
            f["incidents"] = [{"id": inc["id"], "title": inc["title"], "status": status_at(inc, f["tick"])}
                              for inc in incidents if inc["events"][0]["tick"] <= f["tick"]]
        return {"frames": frames, "incidents": incidents, "truth": truth}


ALERT_FACT_KEYS = ("estimate", "capacity", "occupancy_pct", "density", "growth_pct_per_min", "forecast_minutes_to_capacity",
                   "queue_wait_min", "mean_speed", "feed_status", "utilisation", "confidence")
ROUTE_KEYS = ("id", "path", "names", "destination", "destination_name", "edges", "length_m", "est_travel_s", "bottleneck_edge",
              "bottleneck_capacity_ppm", "time_to_move_group_min", "max_zone_pct_on_path", "unverified_zones", "checks",
              "safety_score", "destination_spare")


def slim_plan(plan: dict[str, Any]) -> dict[str, Any]:
    rec = plan.get("recommended")
    return {"source": plan["source"], "purpose": plan["purpose"], "group_size": plan["group_size"],
            "recommended": {k: rec[k] for k in ROUTE_KEYS if k in rec} if rec else None,
            "alternatives_count": len(plan.get("alternatives", [])),
            "shortest_path": {k: plan["shortest_path"][k] for k in ("path", "names", "length_m", "safe", "checks")},
            "allocation": plan["allocation"], "unallocated": plan["unallocated"],
            "rejected_destinations": plan["rejected_destinations"], "explanation": plan["explanation"]}


def compact_frame(snap: dict[str, Any]) -> dict[str, Any]:
    """Keep timeline frames small: alert facts trimmed, route plans summarised (full plans come from crowd.route)."""
    for a in snap["alerts"]:
        a["facts"] = {k: a["facts"][k] for k in ALERT_FACT_KEYS if k in a["facts"]}
    for r in snap["recommendations"]:
        if r.get("route"):
            r["route"] = slim_plan(r["route"])
    for fc in snap["forecasts"].values():
        fc.pop("p_note", None)
    snap.pop("disclaimer", None)
    return snap


def detect_batch(facts: list[dict[str, Any]], rules: list[dict[str, Any]], evaluator: Evaluator,
                 spans: list[tuple[int, int]]) -> list[list[dict[str, Any]]]:
    """One batched rule evaluation for the whole timeline, split back into per-tick alert lists."""
    results = evaluator(rules, facts) if facts else []
    out = []
    for a, b in spans:
        chunk = facts[a:b]
        out.append(detect(chunk, rules, lambda _r, _f, a=a, b=b: results[a:b]))
    return out


def clock(venue: Venue, tick: int) -> str:
    h, m = (int(x) for x in venue.cfg.get("start_clock", "18:00").split(":"))
    total = h * 60 + m + tick * venue.cfg.get("tick_seconds", 60) // 60
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def story_events(cfg: ScenarioConfig) -> list[dict[str, Any]]:
    ev = [{"tick": 0, "kind": "info", "text": "Gates open"},
          {"tick": 15, "kind": "info", "text": "Support act begins on Main Stage"},
          {"tick": 60, "kind": "info", "text": "Headline act begins on Main Stage"}]
    if cfg.exit_blockage:
        ev.append({"tick": cfg.blockage_tick, "kind": "hazard", "text": "East Emergency Exit E1 obstructed by a parked delivery vehicle (simulated)"})
        ev.append({"tick": cfg.blockage_cleared_tick, "kind": "action", "text": "Stewards clear East Emergency Exit E1 (simulated organiser action)"})
    if cfg.intervention:
        ev.append({"tick": cfg.intervention_tick, "kind": "action",
                   "text": "Organisers approve the recommendation (simulated): admissions metered, arrivals signposted to Second Stage and Food Court, stewards guide Main Stage relief"})
    if cfg.feed_outage:
        ev.append({"tick": cfg.outage_start, "kind": "hazard", "text": "Food Court camera CAM-FC stops sending frames (simulated)"})
        ev.append({"tick": cfg.outage_end + 1, "kind": "info", "text": "CAM-FC feed restored"})
    if cfg.detector_glitch:
        ev.append({"tick": cfg.glitch_ticks[0], "kind": "hazard", "text": "Bar queue camera: detector returns errors for 2 minutes (simulated)"})
    return sorted(ev, key=lambda e: e["tick"])


def _first(frames, pred) -> int | None:
    for f in frames:
        if pred(f):
            return f["tick"]
    return None


def incident_lifecycle(cfg: ScenarioConfig, frames: list[dict[str, Any]], venue: Venue) -> list[dict[str, Any]]:
    """Derive incident timelines from the alerts actually raised (organiser actions are simulated and labelled)."""
    auto, ops = "CROWDGUARD (automatic detection)", "Ops lead (simulated organiser action)"
    incidents = []
    high = venue.thresholds["high_pct"]

    def ms_alert(f):
        return any(a["target"] == "main_stage" and a["type"] in ("near_capacity", "overcrowded", "forecast_capacity_breach", "rapid_build_up")
                   for a in f["alerts"])

    t0 = _first(frames, ms_alert)
    if t0 is not None:
        first_alert = next(a for a in frames[t0]["alerts"] if a["target"] == "main_stage")
        ev = [{"tick": t0, "status": "detected", "actor": auto, "note": first_alert["message"]},
              {"tick": t0 + 2, "status": "acknowledged", "actor": ops, "note": "Safety officer reviewing Main Stage build-up"}]
        tf = _first(frames, lambda f: any(a["target"] == "main_stage" and a["type"] == "forecast_capacity_breach" for a in f["alerts"]))
        if tf is not None and tf > t0 + 2:
            msg = next(a["message"] for a in frames[tf]["alerts"] if a["target"] == "main_stage" and a["type"] == "forecast_capacity_breach")
            ev.append({"tick": tf, "status": "acknowledged", "actor": auto, "note": f"Escalated: {msg}; relief plan prepared for approval"})
        if cfg.intervention:
            ev.append({"tick": cfg.intervention_tick, "status": "responding", "actor": ops,
                       "note": "Recommendation approved: meter admissions, redirect arrivals, guide relief to Second Stage / Food Court"})
            below = [f["tick"] for f in frames if f["tick"] > cfg.intervention_tick
                     and (f["readings"]["main_stage"].get("occupancy_pct") or 999) < high]
            if below:
                ev.append({"tick": below[0], "status": "monitoring", "actor": auto, "note": f"Main Stage back below {high:.0f}%"})
                stable = [t for t in below if all(t - k in below for k in range(5))]
                if stable:
                    ev.append({"tick": stable[0], "status": "resolved", "actor": ops, "note": f"Below {high:.0f}% for 5 consecutive minutes"})
        incidents.append({"id": "INC-SIM-001", "title": "Main Stage crowd build-up", "zone": "main_stage", "severity": "critical",
                          "events": sorted(ev, key=lambda e: e["tick"])})
    if cfg.exit_blockage:
        incidents.append({"id": "INC-SIM-002", "title": "East Emergency Exit E1 obstructed", "zone": cfg.blocked_exit, "severity": "critical",
                          "events": [{"tick": cfg.blockage_tick, "status": "detected", "actor": auto, "note": "Exit reported blocked"},
                                     {"tick": cfg.blockage_tick + 1, "status": "acknowledged", "actor": ops, "note": "Stewards dispatched to clear E1"},
                                     {"tick": cfg.blockage_tick + 2, "status": "responding", "actor": ops, "note": "Egress signage switched to West Exit W1 / North Gate"},
                                     {"tick": cfg.blockage_cleared_tick, "status": "resolved", "actor": ops, "note": "Obstruction removed; E1 open"}]})
    if cfg.feed_outage:
        incidents.append({"id": "INC-SIM-003", "title": "Food Court camera feed lost", "zone": cfg.outage_zone, "severity": "medium",
                          "events": [{"tick": cfg.outage_start, "status": "detected", "actor": auto, "note": "No frames from CAM-FC; occupancy unknown"},
                                     {"tick": cfg.outage_start + 1, "status": "acknowledged", "actor": ops, "note": "Steward posted to observe Food Court"},
                                     {"tick": cfg.outage_end + 1, "status": "resolved", "actor": auto, "note": "Feed restored"}]})
    for inc in incidents:
        for e in inc["events"]:
            e["clock"] = clock(venue, e["tick"])
    return incidents


def status_at(inc: dict[str, Any], tick: int) -> str:
    status = "detected"
    for e in inc["events"]:
        if e["tick"] <= tick:
            status = e["status"]
    return status


def run_scenario(venue: Venue, cfg: ScenarioConfig, evaluator: Evaluator) -> dict[str, Any]:
    sim = EventSimulator(venue, cfg)
    result = sim.run(evaluator)
    frames = result["frames"]
    counter_cfg = ScenarioConfig(**{**asdict(cfg), "intervention": False})
    counter_truth = EventSimulator(venue, counter_cfg).run_truth()
    ms_cap = venue.zones.get("main_stage").safe_capacity
    est_series = {z.id: [f["readings"][z.id]["estimate"] for f in frames] for z in venue.zones.zones}
    truth_series = {z.id: [row["truth"][z.id] for row in result["truth"]] for z in venue.zones.zones}
    est_err = {}
    for zid in est_series:
        pairs = [(e, t) for e, t, f in zip(est_series[zid], truth_series[zid], frames)
                 if e is not None and f["readings"][zid]["feed_status"] == "ok"]
        if pairs:
            errs = np.array([e - t for e, t in pairs], dtype=float)
            truths = np.array([t for _, t in pairs], dtype=float)
            est_err[zid] = {"mae": round(float(np.abs(errs).mean()), 1), "bias": round(float(errs.mean()), 1),
                            "mape_pct": round(float((np.abs(errs) / np.maximum(truths, 1)).mean() * 100), 2)}
    ms_est = [v for v in est_series["main_stage"] if v is not None]
    peak = max(range(len(frames)), key=lambda i: frames[i]["readings"]["main_stage"]["estimate"] or 0)
    first_tick = lambda pred: next((f["tick"] for f in frames if pred(f)), None)  # noqa: E731
    milestones = {
        "first_forecast_breach_alert": first_tick(lambda f: any(a["type"] == "forecast_capacity_breach" and a["target"] == "main_stage" for a in f["alerts"])),
        "first_rapid_build_up_alert": first_tick(lambda f: any(a["type"] == "rapid_build_up" and a["target"] == "main_stage" for a in f["alerts"])),
        "first_near_capacity_alert": first_tick(lambda f: any(a["type"] == "near_capacity" and a["target"] == "main_stage" for a in f["alerts"])),
        "first_overcrowded_alert": first_tick(lambda f: any(a["type"] == "overcrowded" and a["target"] == "main_stage" for a in f["alerts"])),
        "first_relief_route": first_tick(lambda f: any(r["action_type"] == "relieve_zone" and r["target"] == "main_stage" and (r.get("route") or {}).get("recommended") for r in f["recommendations"])),
        "exit_blocked_alert": first_tick(lambda f: any(a["type"] == "exit_blocked" for a in f["alerts"])),
        "stale_feed_alert": first_tick(lambda f: any(a["type"] == "stale_feed" for a in f["alerts"])),
    }
    return {
        "scenario": {**asdict(cfg), "label": "SYNTHETIC SIMULATION — deterministic, reproducible, not real data",
                     "venue": venue.name, "ticks": len(frames), "tick_seconds": venue.cfg.get("tick_seconds", 60),
                     "start_clock": venue.cfg.get("start_clock", "18:00")},
        "frames": frames,
        "incidents": result["incidents"],
        "events": story_events(cfg),
        "counterfactual": {"label": "Same scenario with no organiser intervention (synthetic truth)",
                           "main_stage": [row["truth"]["main_stage"] for row in counter_truth],
                           "peak": max(row["truth"]["main_stage"] for row in counter_truth),
                           "peak_pct": round(max(row["truth"]["main_stage"] for row in counter_truth) / ms_cap * 100, 1)},
        "evaluation": {
            "estimation_error_vs_synthetic_truth": est_err,
            "main_stage_forecast_backtest": rolling_backtest(ms_est, ms_cap, horizon=10),
            "main_stage_peak": {"tick": frames[peak]["tick"], "clock": frames[peak]["clock"],
                                "estimate": frames[peak]["readings"]["main_stage"]["estimate"],
                                "pct": frames[peak]["readings"]["main_stage"]["occupancy_pct"]},
            "milestones": {k: ({"tick": v, "clock": clock(venue, v)} if v is not None else None) for k, v in milestones.items()},
            "note": "Errors are measured against the simulator's hidden truth; they say nothing about accuracy on real cameras.",
        },
    }
