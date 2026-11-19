"""Safety-weighted route planning over the venue graph (NetworkX).

Principles enforced in code (and covered by tests):
  * A route never enters a zone that is already high or critical, other than the zone being relieved.
  * A destination must have fresh data and enough spare capacity (judged on the *upper* estimate)
    to stay at or below ``destination_max_pct`` after receiving people.
  * Blocked edges and blocked nodes (e.g. an obstructed exit) are removed from the graph.
  * The distance-only shortest path is computed separately and *assessed*; it is never presented
    as safe just because it is short. When it fails a check, the reasons are reported.
  * The planner only proposes movement. It never proposes closing or restricting an exit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Literal

import networkx as nx

from .crowd_flow import FREE_SPEED_MPS, walking_speed
from .density_estimator import BAND_RANK
from .venue import Venue

Purpose = Literal["relieve", "egress"]
UNSAFE_BANDS = {"high", "critical"}
# Concourses are circulation/egress space and are never used as holding areas.
RELIEF_DEST_KINDS = {"stage", "amenity"}


@dataclass
class RouteState:
    """Current conditions the planner reasons about. ``zones`` maps zone id -> reading fields
    (estimate, upper, occupancy_pct, upper_pct, band, feed_status, density_ppm2, carried_forward, age_s)."""

    zones: dict[str, dict[str, Any]]
    edge_utilisation: dict[str, float] = field(default_factory=dict)
    blocked_edges: set[str] = field(default_factory=set)
    blocked_nodes: set[str] = field(default_factory=set)


class RouteOptimizer:
    def __init__(self, venue: Venue) -> None:
        self.venue = venue
        self.th = venue.thresholds

    # ---- zone checks ---------------------------------------------------------
    def _zone(self, state: RouteState, nid: str) -> dict[str, Any] | None:
        return state.zones.get(nid) if self.venue.nodes[nid]["kind"] == "zone" else None

    def _fresh(self, z: dict[str, Any] | None) -> bool:
        return bool(z) and z.get("feed_status") == "ok" and not z.get("carried_forward") and z.get("estimate") is not None

    def _unsafe(self, z: dict[str, Any] | None) -> bool:
        return bool(z) and z.get("band") in UNSAFE_BANDS

    def _unknown(self, z: dict[str, Any] | None) -> bool:
        return z is not None and (z.get("band") == "unknown" or z.get("estimate") is None or not self._fresh(z))

    def spare_for(self, state: RouteState, zid: str) -> int | None:
        z = state.zones.get(zid)
        zone = self.venue.zones.get(zid)
        if not z or zone is None or z.get("upper") is None:
            return None
        return int(zone.safe_capacity * self.th["destination_max_pct"] / 100.0 - z["upper"])

    # ---- graph weighting ------------------------------------------------------
    def _weight(self, state: RouteState, source: str):
        def w(u: str, v: str, d: dict[str, Any]) -> float | None:
            if d["id"] in state.blocked_edges or v in state.blocked_nodes or u in state.blocked_nodes:
                return None
            zv = self._zone(state, v)
            if v != source and self._unsafe(zv):
                return None  # hard rule: never route through or into an overcrowded zone
            dens = [x.get("density_ppm2") for x in (self._zone(state, u), zv) if x and x.get("density_ppm2") is not None]
            speed = walking_speed(max(dens)) if dens else FREE_SPEED_MPS
            t = d["length_m"] / max(speed or FREE_SPEED_MPS, 0.15)
            util = state.edge_utilisation.get(d["id"], 0.0)
            if util > 0.7:
                t *= 1 + 5 * (util - 0.7)
            if zv is not None and v != source:
                pct = zv.get("occupancy_pct") or 0.0
                if pct > self.th["elevated_pct"]:
                    t += 60.0 * (pct - self.th["elevated_pct"]) / 15.0
                if self._unknown(zv):
                    t += 90.0
            return t
        return w

    def _route_record(self, state: RouteState, path: list[str], group: int, source: str, rid: str) -> dict[str, Any]:
        g = self.venue.graph
        edges = [g.edges[a, b] for a, b in zip(path, path[1:])]
        length = sum(e["length_m"] for e in edges)
        wfn = self._weight(state, source)
        travel = sum(wfn(a, b, g.edges[a, b]) or 0.0 for a, b in zip(path, path[1:]))
        avail = []
        for e in edges:
            util = state.edge_utilisation.get(e["id"], 0.0)
            avail.append((max(0.1, 1 - util) * e["capacity_ppm"], e))
        bottleneck_cap, bottleneck = min(avail, key=lambda x: x[0]) if avail else (None, None)
        zones_on = [n for n in path[1:] if self.venue.nodes[n]["kind"] == "zone"]
        pcts = [(state.zones.get(n) or {}).get("occupancy_pct") for n in zones_on]
        pcts_known = [p for p in pcts if p is not None]
        unverified = [n for n in zones_on if self._unknown(state.zones.get(n))]
        # A zone destination may take part of the group (the rest is allocated elsewhere).
        spare = self.spare_for(state, path[-1]) if self.venue.nodes[path[-1]]["kind"] == "zone" else None
        share = min(group, spare) if spare is not None and spare > 0 else group
        checks = self.assess_path(state, path, source, share, purpose=None)["checks"]
        score = 100.0
        score -= max(0.0, (max(pcts_known) if pcts_known else 0) - 50) * 0.8
        score -= 12 * len(unverified)
        score -= 15 * sum(1 for c in checks if not c["passed"])
        score -= min(20.0, length / 25.0)
        return {
            "id": rid, "path": path, "names": [self.venue.name_of(n) for n in path], "destination": path[-1],
            "destination_name": self.venue.name_of(path[-1]), "edges": [e["id"] for e in edges],
            "length_m": round(length, 1), "est_travel_s": round(travel), "bottleneck_edge": bottleneck["id"] if bottleneck else None,
            "bottleneck_capacity_ppm": round(bottleneck_cap, 1) if bottleneck_cap else None,
            "time_to_move_group_min": round(group / bottleneck_cap, 1) if bottleneck_cap and group else None,
            "max_zone_pct_on_path": max(pcts_known) if pcts_known else None, "unverified_zones": unverified,
            "destination_spare": spare,
            "checks": checks, "safety_score": round(max(0.0, min(100.0, score))),
            "score_note": "heuristic ranking score, not a probability of safety",
        }

    def assess_path(self, state: RouteState, path: list[str], source: str, group: int,
                    purpose: Purpose | None) -> dict[str, Any]:
        """Check a path against every hard safety rule; returns pass/fail per check with detail."""
        g = self.venue.graph
        checks = []
        blocked_e = [g.edges[a, b]["id"] for a, b in zip(path, path[1:]) if g.edges[a, b]["id"] in state.blocked_edges]
        blocked_n = [n for n in path if n in state.blocked_nodes]
        checks.append({"name": "no blocked corridors or exits", "passed": not blocked_e and not blocked_n,
                       "detail": "clear" if not blocked_e and not blocked_n else
                       "blocked: " + ", ".join([self.venue.name_of(n) for n in blocked_n] + blocked_e)})
        crowded = [n for n in path[1:] if self._unsafe(self._zone(state, n))]
        checks.append({"name": "does not enter an overcrowded zone", "passed": not crowded,
                       "detail": "none on path" if not crowded else ", ".join(
                           f"{self.venue.name_of(n)} ({state.zones[n].get('occupancy_pct')}%)" for n in crowded)})
        dest = path[-1]
        dnode = self.venue.nodes[dest]
        if dnode["kind"] == "zone":
            spare = self.spare_for(state, dest)
            fresh = self._fresh(state.zones.get(dest))
            checks.append({"name": "destination data is fresh", "passed": fresh,
                           "detail": "live reading" if fresh else "destination feed stale or missing: occupancy unverified"})
            ok = spare is not None and spare >= max(1, group)
            checks.append({"name": f"destination stays ≤ {self.th['destination_max_pct']:.0f}% after arrival", "passed": ok,
                           "detail": f"spare capacity {spare} (upper estimate) for {group} people" if spare is not None else "unknown"})
        else:
            checks.append({"name": "destination exit is open", "passed": dest not in state.blocked_nodes,
                           "detail": "open" if dest not in state.blocked_nodes else "blocked"})
        unverified = [n for n in path[1:-1] if self._unknown(self._zone(state, n))]
        checks.append({"name": "intermediate zones have live data", "passed": not unverified,
                       "detail": "all live" if not unverified else "unverified: " + ", ".join(self.venue.name_of(n) for n in unverified)})
        return {"checks": checks, "safe": all(c["passed"] for c in checks)}

    # ---- destinations --------------------------------------------------------
    def _destinations(self, state: RouteState, source: str, purpose: Purpose, group: int) -> tuple[list[str], list[dict[str, Any]]]:
        ok, rejected = [], []
        if purpose == "egress":
            for n in self.venue.exits():
                if n["id"] in state.blocked_nodes:
                    rejected.append({"id": n["id"], "name": n["name"], "reason": "exit blocked / unavailable"})
                else:
                    ok.append(n["id"])
            return ok, rejected
        for zone in self.venue.zones.zones:
            if zone.id == source or zone.kind not in RELIEF_DEST_KINDS:
                continue
            z = state.zones.get(zone.id)
            if z is None or z.get("estimate") is None:
                rejected.append({"id": zone.id, "name": zone.name, "reason": "no occupancy data (unknown is not empty)"})
            elif not self._fresh(z):
                rejected.append({"id": zone.id, "name": zone.name, "reason": f"feed {z.get('feed_status')}: occupancy unverified"})
            elif self._unsafe(z):
                rejected.append({"id": zone.id, "name": zone.name, "reason": f"already {z['band']} ({z.get('occupancy_pct')}%)"})
            elif zone.id in state.blocked_nodes:
                rejected.append({"id": zone.id, "name": zone.name, "reason": "closed"})
            else:
                spare = self.spare_for(state, zone.id) or 0
                if spare < max(1, min(group, 50)):
                    rejected.append({"id": zone.id, "name": zone.name,
                                     "reason": f"insufficient spare capacity ({max(spare, 0)} below the {self.th['destination_max_pct']:.0f}% limit)"})
                else:
                    ok.append(zone.id)
        return ok, rejected

    # ---- main entry ----------------------------------------------------------
    def plan(self, state: RouteState, source: str, purpose: Purpose = "relieve", group_size: int = 500,
             k: int = 3) -> dict[str, Any]:
        if source not in self.venue.nodes:
            raise ValueError(f"Unknown source '{source}'")
        g = self.venue.graph
        wfn = self._weight(state, source)
        dests, rejected = self._destinations(state, source, purpose, group_size)
        explanation: list[str] = []

        # Distance-only shortest path to the nearest destination of this purpose (ignores all safety).
        if purpose == "egress":
            naive_targets = [n["id"] for n in self.venue.exits()]
        else:
            naive_targets = [z.id for z in self.venue.zones.zones if z.id != source and z.kind in RELIEF_DEST_KINDS]
        lengths = nx.single_source_dijkstra_path_length(g, source, weight="length_m")
        naive_dest = min(naive_targets, key=lambda n: lengths.get(n, float("inf")))
        naive_path = nx.shortest_path(g, source, naive_dest, weight="length_m")
        naive_spare = self.spare_for(state, naive_dest) if self.venue.nodes[naive_dest]["kind"] == "zone" else None
        naive_share = min(group_size, naive_spare) if naive_spare is not None and naive_spare > 0 else group_size
        naive_eval = self.assess_path(state, naive_path, source, naive_share, purpose)
        shortest = {"path": naive_path, "names": [self.venue.name_of(n) for n in naive_path], "destination": naive_dest,
                    "length_m": round(lengths[naive_dest], 1), "can_take": naive_share if naive_spare is not None else None,
                    **naive_eval}

        candidates: list[tuple[float, list[str]]] = []
        try:
            dist, paths = nx.single_source_dijkstra(g, source, weight=wfn)
        except nx.NetworkXException:
            dist, paths = {}, {}
        for d in dests:
            if d in paths and d != source:
                candidates.append((dist[d], paths[d]))
        candidates.sort(key=lambda c: c[0])
        # Extra distinct paths to the best destination (k-shortest simple paths on the safe graph).
        if candidates:
            best_dest = candidates[0][1][-1]
            safe_g = nx.Graph()
            safe_g.add_nodes_from(g.nodes)
            for a, b, d in g.edges(data=True):
                for u, v in ((a, b), (b, a)):
                    c = wfn(u, v, d)
                    if c is not None:
                        prev = safe_g.edges[a, b]["w"] if safe_g.has_edge(a, b) else None
                        safe_g.add_edge(a, b, w=c if prev is None else max(prev, c))
            try:
                for p in islice(nx.shortest_simple_paths(safe_g, source, best_dest, weight="w"), 1, k):
                    if all(p != c[1] for c in candidates):
                        candidates.append((sum(safe_g.edges[a, b]["w"] for a, b in zip(p, p[1:])), p))
            except nx.NetworkXException:
                pass
        candidates.sort(key=lambda c: c[0])
        routes = [self._route_record(state, p, group_size, source, f"R{i + 1}") for i, (_, p) in enumerate(candidates[: max(k, 1) + 2])]
        routes = [r for r in routes if all(c["passed"] for c in r["checks"] if c["name"] != "intermediate zones have live data")]
        recommended = routes[0] if routes else None

        allocation, unallocated = [], 0
        if purpose == "relieve" and routes:
            remaining = group_size
            used_dest: set[str] = set()
            for r in routes:
                if remaining <= 0:
                    break
                if r["destination"] in used_dest:
                    continue
                spare = max(0, self.spare_for(state, r["destination"]) or 0)
                take = min(remaining, spare)
                if take > 0:
                    allocation.append({"destination": r["destination"], "destination_name": r["destination_name"],
                                       "people": int(take), "route_id": r["id"], "via": r["names"][1:-1]})
                    used_dest.add(r["destination"])
                    remaining -= take
            unallocated = max(0, int(remaining))

        if recommended:
            explanation.append(f"Recommended {recommended['id']}: {' → '.join(recommended['names'])} "
                               f"({recommended['length_m']:.0f} m, ~{recommended['est_travel_s'] / 60:.1f} min walk at current densities).")
            if recommended["bottleneck_capacity_ppm"]:
                explanation.append(f"Throughput is limited by {recommended['bottleneck_edge']} "
                                   f"(~{recommended['bottleneck_capacity_ppm']:.0f} people/min available); moving {group_size} people takes "
                                   f"~{recommended['time_to_move_group_min']} min.")
            if recommended["unverified_zones"]:
                explanation.append("Caution: passes zones without live data (" + ", ".join(
                    self.venue.name_of(z) for z in recommended["unverified_zones"]) + "); confirm conditions with stewards first.")
        else:
            explanation.append("No route satisfies every safety rule. Do not move people; hold inflow and escalate to the safety officer.")
        if naive_eval["safe"] and recommended and recommended["path"] == naive_path:
            explanation.append("The recommended route is also the distance-shortest path; it was accepted because it passed every safety check, not because it is short.")
        elif not naive_eval["safe"]:
            failed = [f"{c['name']} ({c['detail']})" for c in naive_eval["checks"] if not c["passed"]]
            explanation.append(f"The distance-shortest path ({' → '.join(shortest['names'])}, {shortest['length_m']:.0f} m) was rejected: " + "; ".join(failed) + ".")
        elif recommended:
            explanation.append(f"The distance-shortest path ({shortest['length_m']:.0f} m) passes the hard checks but scores worse on congestion and travel time.")
        if unallocated:
            explanation.append(f"{unallocated} of {group_size} people cannot be placed without pushing a destination above "
                               f"{self.th['destination_max_pct']:.0f}%: reduce inflow at the entrances instead.")
        return {"source": source, "source_name": self.venue.name_of(source), "purpose": purpose, "group_size": group_size,
                "recommended": recommended, "alternatives": routes[1:], "shortest_path": shortest,
                "allocation": allocation, "unallocated": unallocated, "rejected_destinations": rejected,
                "explanation": explanation, "blocked_edges": sorted(state.blocked_edges), "blocked_nodes": sorted(state.blocked_nodes),
                "advisory": "Route suggestions are advisory. Stewards and the safety officer decide and direct any movement."}


def rank(band: str | None) -> int:
    return BAND_RANK.get(band or "unknown", -1)
