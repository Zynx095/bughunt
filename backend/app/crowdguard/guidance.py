"""Route guidance on the site's navigation grid (NetworkX A*), with hysteresis.

The walkable cells of the occupancy grid form an 8-connected graph (no corner-cutting past blocked
cells). Each update the planner prices every edge from the live occupancy:

    cost = length · (1 + 3·density_index) + 25 m per unknown cell   (unknown is not assumed empty)

and finds the cheapest path from the origin to every *usable* exit with A* (Euclidean heuristic).
Hard rules: blocked / restricted cells are not in the graph; congested cells are excluded (the planner
only falls back to crossing them, flagged, if nothing else exists); an exit is unusable when an
operator marked it unavailable or its approach is congested. The distance-only path is computed too,
so the UI can show what the naive route would cross.

`GuidanceController` keeps a recommendation stable: it switches only when the current route becomes
invalid, or when a new route has been at least 15 % cheaper for 3 consecutive updates and the
current one has been held for 5 s. Every recommendation needs a human organiser's approval.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import networkx as nx
import numpy as np

from .site_model import Portal, SiteMasks, SiteModel

Cell = tuple[int, int]
UNKNOWN_PENALTY_M = 25.0
SWITCH_GAIN = 0.15
SWITCH_CONFIRMATIONS = 3
MIN_HOLD_S = 5.0


class RoutePlanner:
    def __init__(self, site: SiteModel, masks: SiteMasks) -> None:
        self.site = site
        self.masks = masks
        g = nx.Graph()
        rows, cols = site.rows, site.cols
        for r in range(rows):
            for c in range(cols):
                if masks.blocked[r, c]:
                    continue
                g.add_node((r, c))
                for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                    r2, c2 = r + dr, c + dc
                    if not (0 <= r2 < rows and 0 <= c2 < cols) or masks.blocked[r2, c2]:
                        continue
                    if dr and dc and (masks.blocked[r + dr, c] or masks.blocked[r, c + dc]):
                        continue  # no corner cutting past an obstacle
                    g.add_edge((r, c), (r2, c2), length=site.cell_m * (math.sqrt(2) if dr and dc else 1.0))
        self.graph = g

    def nearest_open(self, p: tuple[float, float]) -> Optional[Cell]:
        r0, c0 = self.site.cell_of(p)
        best, bd = None, float("inf")
        for n in self.graph.nodes:
            d = (n[0] - r0) ** 2 + (n[1] - c0) ** 2
            if d < bd:
                best, bd = n, d
        return best

    def to_point(self, n: Cell) -> tuple[float, float]:
        return (round((n[1] + 0.5) * self.site.cell_m, 2), round((n[0] + 0.5) * self.site.cell_m, 2))

    def _weights(self, state: np.ndarray, index: np.ndarray, allow_congested: bool):
        def w(u: Cell, v: Cell, d: dict[str, Any]) -> Optional[float]:
            sv = state[v]
            if sv == "C" and not allow_congested:
                return None
            cost = d["length"] * (1.0 + 3.0 * float(min(index[v], 3.0)))
            if sv == "U":
                cost += UNKNOWN_PENALTY_M
            if sv == "C":
                cost += 200.0
            return cost
        return w

    def _heuristic(self, a: Cell, b: Cell) -> float:
        return self.site.cell_m * math.hypot(a[0] - b[0], a[1] - b[1])

    def path_cost(self, path: list[Cell], state: np.ndarray, index: np.ndarray) -> Optional[float]:
        w = self._weights(state, index, allow_congested=False)
        total = 0.0
        for u, v in zip(path, path[1:]):
            if not self.graph.has_edge(u, v):
                return None
            c = w(u, v, self.graph.edges[u, v])
            if c is None:
                return None
            total += c
        return total

    def exit_status(self, p: Portal, state: np.ndarray) -> tuple[bool, str]:
        if not p.available:
            return False, "reported unavailable by an operator"
        cell = self.nearest_open(p.center)
        if cell is None:
            return False, "no walkable cell reaches it"
        r0, c0 = cell
        reach = max(1, int(round(1.5 / self.site.cell_m)))
        win = state[max(0, r0 - reach): r0 + reach + 1, max(0, c0 - reach): c0 + reach + 1]
        if np.count_nonzero(win == "C") > 0.5 * np.count_nonzero(win != "B"):
            return False, "approach is congested"
        return True, "open"

    def plan(self, origin: tuple[float, float], state: np.ndarray, index: np.ndarray) -> dict[str, Any]:
        start = self.nearest_open(origin)
        exits = [p for p in self.site.portals if p.kind in ("exit", "emergency_exit")]
        rejected, options = [], []
        if start is None:
            return {"ok": False, "reason": "origin is not on walkable ground", "rejected": rejected}
        if np.all((state == "U") | (state == "B")):
            return {"ok": False, "reason": "no live observation of the area: guidance is unavailable while the feed is down", "rejected": rejected}
        for allow_c in (False, True):
            w = self._weights(state, index, allow_c)
            for p in exits:
                usable, why = self.exit_status(p, state)
                if not usable:
                    if not allow_c:
                        rejected.append({"id": p.id, "name": p.name, "reason": why})
                    continue
                goal = self.nearest_open(p.center)
                try:
                    path = nx.astar_path(self.graph, start, goal, heuristic=self._heuristic, weight=w)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                cost = sum(w(u, v, self.graph.edges[u, v]) or 0.0 for u, v in zip(path, path[1:]))
                options.append({"exit": p, "path": path, "cost": cost, "crosses_congestion": allow_c})
            if options:
                break
        if not options:
            return {"ok": False, "reason": "no exit can be reached without blocked or congested ground", "rejected": rejected}
        options.sort(key=lambda o: o["cost"])
        best = options[0]
        # Distance-only path to the nearest exit (what people would do without guidance).
        naive = None
        try:
            naive_targets = [(p, self.nearest_open(p.center)) for p in exits]
            lens = nx.single_source_dijkstra_path_length(self.graph, start, weight="length")
            p_near, goal = min(((p, g) for p, g in naive_targets if g in lens), key=lambda pg: lens[pg[1]])
            npath = nx.astar_path(self.graph, start, goal, heuristic=self._heuristic, weight="length")
            congested = [self.to_point(n) for n in npath if state[n] == "C"]
            unknown = sum(1 for n in npath if state[n] == "U")
            naive = {"exit_id": p_near.id, "exit_name": p_near.name, "points": [self.to_point(n) for n in npath],
                     "length_m": round(sum(self.graph.edges[u, v]["length"] for u, v in zip(npath, npath[1:])), 1),
                     "congested_points": congested, "unknown_cells": unknown}
        except (ValueError, nx.NetworkXException):
            pass
        return {"ok": True, "best": best, "options": options, "naive": naive, "rejected": rejected, "start": start}


class GuidanceController:
    """Holds the current recommendation and applies hysteresis before changing it."""

    def __init__(self, planner: RoutePlanner) -> None:
        self.planner = planner
        self.current: Optional[dict[str, Any]] = None
        self.since: float = 0.0
        self.better_streak = 0

    def reset(self) -> None:
        self.current, self.better_streak = None, 0

    def update(self, origin: tuple[float, float], origin_label: str, state: np.ndarray, index: np.ndarray, now: float) -> tuple[dict[str, Any], Optional[str]]:
        """Returns (recommendation for the UI, change message or None)."""
        plan = self.planner.plan(origin, state, index)
        changed: Optional[str] = None
        if not plan["ok"]:
            if self.current is not None:
                changed = f"Route withdrawn: {plan['reason']}"
            self.current = None
            return {"available": False, "reason": plan["reason"], "rejected_exits": plan["rejected"], "origin": origin_label,
                    "advisory": "No guidance is better than wrong guidance: confirm conditions with stewards."}, changed
        best = plan["best"]
        cur = self.current
        if cur is not None and cur["start"] != plan["start"]:
            cur = None  # origin moved: start afresh
        if cur is None:
            self._adopt(best, plan["start"], now)
        else:
            cur_cost = self.planner.path_cost(cur["path"], state, index)
            # Re-read the exit from the live site config (an operator may have marked it unavailable).
            cur["exit"] = next((p for p in self.planner.site.portals if p.id == cur["exit"].id), cur["exit"])
            exit_ok, why = self.planner.exit_status(cur["exit"], state)
            if cur_cost is None or not exit_ok:
                reason = (f"{cur['exit'].name} is no longer usable ({why})" if not exit_ok
                          else "the current route now crosses congested or blocked ground")
                self._adopt(best, plan["start"], now)
                changed = f"Route changed to {best['exit'].name}: {reason}"
            else:
                cur["cost"] = cur_cost
                if best["path"] != cur["path"] and best["cost"] < cur_cost * (1 - SWITCH_GAIN):
                    self.better_streak += 1
                    if self.better_streak >= SWITCH_CONFIRMATIONS and now - self.since >= MIN_HOLD_S:
                        gain = (1 - best["cost"] / cur_cost) * 100
                        self._adopt(best, plan["start"], now)
                        changed = f"Route changed to {best['exit'].name}: {gain:.0f}% lower crowd-weighted cost, sustained"
                else:
                    self.better_streak = 0
        rec = self.current
        pts = [self.planner.to_point(n) for n in rec["path"]]
        length = sum(self.planner.graph.edges[u, v]["length"] for u, v in zip(rec["path"], rec["path"][1:]))
        reasons = []
        naive = plan["naive"]
        if naive and naive["congested_points"]:
            reasons.append(f"The direct way to {naive['exit_name']} crosses {len(naive['congested_points'])} congested cell(s).")
        if naive and naive["exit_id"] == rec["exit"].id and not naive["congested_points"]:
            reasons.append("Direct route is clear; it is recommended because it is uncongested, not because it is short.")
        for rj in plan["rejected"]:
            reasons.append(f"{rj['name']} not used: {rj['reason']}.")
        if rec.get("crosses_congestion"):
            reasons.append("Every route crosses congestion: hold movement and send stewards before guiding people.")
        unknown = sum(1 for n in rec["path"] if state[n] == "U")
        if unknown:
            reasons.append(f"Passes {unknown} cell(s) the camera cannot see: confirm with a steward.")
        return {
            "available": True, "origin": origin_label, "exit_id": rec["exit"].id, "exit_name": rec["exit"].name,
            "exit_kind": rec["exit"].kind, "points": pts, "length_m": round(length, 1),
            "walk_s": round(length / 1.2), "cost": round(rec["cost"], 1),
            "held_s": round(now - self.since, 1), "pending_switch": self.better_streak,
            "naive": naive, "rejected_exits": plan["rejected"], "reasons": reasons,
            "advisory": "Advisory only: an organiser decides whether to direct people along this route.",
        }, changed

    def _adopt(self, best: dict[str, Any], start: Cell, now: float) -> None:
        self.current = {**best, "start": start}
        self.since = now
        self.better_streak = 0
