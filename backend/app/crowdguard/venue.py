"""Venue model: zones, junctions, gates and exits as a weighted NetworkX graph."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

from .density_estimator import DEFAULT_THRESHOLDS
from .zone_manager import ZoneManager

SAMPLE_VENUE = Path(__file__).resolve().parent.parent.parent / "sample_data" / "crowdguard_venue.json"
# Planning flow rate for level corridors (persons per metre of clear width per minute).
SPECIFIC_FLOW_PPM_PER_M = {"corridor": 82.0, "gate": 82.0, "exit": 82.0, "stairs": 66.0}


class Venue:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.id = cfg.get("id", "venue")
        self.name = cfg.get("name", self.id)
        self.synthetic = bool(cfg.get("synthetic", False))
        self.thresholds = {**DEFAULT_THRESHOLDS, **cfg.get("thresholds", {})}
        self.zones = ZoneManager.from_config(cfg["zones"])
        self.nodes: dict[str, dict[str, Any]] = {}
        for z in self.zones.zones:
            self.nodes[z.id] = {"id": z.id, "name": z.name, "kind": "zone", "zone_kind": z.kind,
                                "pos": list(z.centroid), "entrance": False, "exit": False, "emergency_exit": False}
        for n in cfg.get("nodes", []):
            if n["id"] in self.nodes:
                raise ValueError(f"Duplicate node id '{n['id']}'")
            self.nodes[n["id"]] = {"entrance": False, "exit": False, "emergency_exit": False, **n}
        self.edges: dict[str, dict[str, Any]] = {}
        for e in cfg.get("edges", []):
            if e["a"] not in self.nodes or e["b"] not in self.nodes:
                raise ValueError(f"Edge '{e['id']}' references an unknown node")
            cap = float(e.get("capacity_ppm") or e["width_m"] * SPECIFIC_FLOW_PPM_PER_M.get(e.get("kind", "corridor"), 82.0))
            self.edges[e["id"]] = {**e, "capacity_ppm": round(cap, 1)}
        self.graph = self._build_graph()

    def _build_graph(self) -> nx.Graph:
        g = nx.Graph()
        for nid, n in self.nodes.items():
            g.add_node(nid, **n)
        for eid, e in self.edges.items():
            g.add_edge(e["a"], e["b"], id=eid, length_m=float(e["length_m"]), width_m=float(e["width_m"]),
                       capacity_ppm=e["capacity_ppm"], kind=e.get("kind", "corridor"))
        if not nx.is_connected(g):
            raise ValueError("Venue graph must be connected")
        return g

    # ---- helpers -----------------------------------------------------------
    def pos(self) -> dict[str, list[float]]:
        return {nid: n["pos"] for nid, n in self.nodes.items()}

    def edge_between(self, a: str, b: str) -> dict[str, Any]:
        return self.edges[self.graph.edges[a, b]["id"]]

    def neighbours(self, nid: str) -> list[str]:
        return list(self.graph.neighbors(nid))

    def exits(self) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n.get("exit")]

    def entrances(self) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n.get("entrance")]

    def is_emergency_exit(self, nid: str) -> bool:
        return bool(self.nodes.get(nid, {}).get("emergency_exit"))

    def name_of(self, nid: str) -> str:
        return self.nodes.get(nid, {}).get("name", nid)

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "synthetic": self.synthetic, "canvas": self.cfg.get("canvas"),
                "start_clock": self.cfg.get("start_clock"), "tick_seconds": self.cfg.get("tick_seconds", 60),
                "thresholds": self.thresholds, "zones": self.zones.describe(),
                "nodes": list(self.nodes.values()), "edges": list(self.edges.values()),
                "camera_layouts": self.cfg.get("camera_layouts", {}),
                "graph": {"nodes": self.graph.number_of_nodes(), "edges": self.graph.number_of_edges(),
                          "library": f"networkx {nx.__version__}"}}


@lru_cache(maxsize=1)
def _sample_cfg_text() -> str:
    return SAMPLE_VENUE.read_text(encoding="utf-8")


def load_venue(cfg: dict[str, Any] | None = None) -> Venue:
    return Venue(cfg if cfg is not None else json.loads(_sample_cfg_text()))


def sample_venue_config() -> dict[str, Any]:
    return json.loads(_sample_cfg_text())
