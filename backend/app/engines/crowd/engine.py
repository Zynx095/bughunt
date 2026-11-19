"""Crowd engine (CROWDGUARD): exposes the crowd-safety services as typed, policy-checked operations.

It reuses the other engines through the registry instead of re-implementing them:
  decision.evaluate_rules (alert rules) · ml.forecast (backtested forecasting) · ai.explain (narrative,
  Gemini when configured, local fallback otherwise) · crypto.hash / crypto.merkle_root (incident evidence).
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation
from app.crowdguard.analysis import analyse_snapshot
from app.crowdguard.congestion_detector import Evaluator, local_evaluator
from app.crowdguard.crowd_detection import find_weights, get_detector
from app.crowdguard.crowd_forecaster import forecast_zone, rolling_backtest
from app.crowdguard.density_estimator import Observation, assess_reading
from app.crowdguard.media_analysis import analyse_media
from app.crowdguard.route_optimizer import RouteOptimizer, RouteState
from app.crowdguard.safety_recommendations import DISCLAIMER
from app.crowdguard.simulation import ScenarioConfig, run_scenario
from app.crowdguard.venue import Venue, load_venue
from app.db.models import utcnow_iso
from app.db.store import canonical_json

GENESIS = "0" * 64
INCIDENT_FLOW = {
    "acknowledge": ({"detected"}, "acknowledged"),
    "respond": ({"acknowledged", "monitoring", "resolved"}, "responding"),
    "monitor": ({"responding"}, "monitoring"),
    "resolve": ({"acknowledged", "responding", "monitoring"}, "resolved"),
    "close": ({"resolved"}, "closed"),
    "note": ({"detected", "acknowledged", "responding", "monitoring", "resolved"}, None),
}
# Shared progress board for long media jobs (written by the operation, read by the API).
MEDIA_PROGRESS: dict[str, dict[str, Any]] = {}


class EmptyInput(BaseModel):
    pass


class SimulateInput(BaseModel):
    seed: int = Field(2026, ge=0, le=2**31 - 1)
    intervention: bool = True
    exit_blockage: bool = True
    feed_outage: bool = True
    detector_glitch: bool = True
    tick: int | None = Field(None, ge=0, description="Return only this tick (plus history) instead of the full timeline")


class ObservationIn(BaseModel):
    zone_id: str
    observed_count: int | None = Field(None, ge=0, le=1_000_000)
    feed_status: Literal["ok", "stale", "missing", "detector_error"] = "ok"
    coverage: float = Field(1.0, gt=0, le=1)
    detector_confidence: float | None = Field(None, ge=0, le=1)
    tracking_stability: float | None = Field(None, ge=0, le=1)
    source: Literal["video", "image", "manual", "simulation"] = "manual"
    age_s: float | None = Field(None, ge=0)


class AssessInput(BaseModel):
    observations: list[ObservationIn] = Field(..., max_length=200)
    history: dict[str, list[float | None]] = Field(default_factory=dict, description="Prior estimates per zone, oldest first")
    exit_status: dict[str, Literal["open", "blocked"]] = Field(default_factory=dict)
    edge_flows: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    t: float = 0.0


class RouteInput(BaseModel):
    source: str
    purpose: Literal["relieve", "egress"] = "relieve"
    group_size: int = Field(500, ge=1, le=100_000)
    zones: dict[str, dict[str, Any]] | None = Field(None, description="Zone readings; omit to use the simulation tick")
    tick: int | None = Field(None, ge=0, description="Simulation tick to take conditions from (default scenario)")
    blocked_edges: list[str] = Field(default_factory=list, max_length=200)
    blocked_nodes: list[str] = Field(default_factory=list, max_length=200)
    edge_utilisation: dict[str, float] | None = None
    k: int = Field(3, ge=1, le=6)


class ForecastInput(BaseModel):
    zone_id: str
    history: list[float] | None = Field(None, max_length=10_000, description="Estimates, oldest first; omit to use the simulation")
    tick: int | None = Field(None, ge=0)
    horizon: int = Field(15, ge=1, le=120)
    use_ml: bool = True


class MediaInput(BaseModel):
    document_id: str
    layout: str | None = Field("default_two_zone", description="Name of a venue camera layout")
    custom_layout: dict[str, Any] | None = Field(None, description="Layout object (overrides 'layout')")
    venue_zone: str | None = Field(None, description="Venue zone this camera observes (applies to every camera zone)")
    coverage: float | None = Field(None, gt=0, le=1, description="Fraction of the venue zone the camera sees")
    max_seconds: float = Field(30, gt=0, le=120)
    target_fps: float = Field(5, gt=0, le=15)
    heatmap_mode: Literal["gaussian", "point", "zone", "movement"] = "gaussian"
    sigma: float = Field(28.0, ge=5, le=80)
    job_id: str | None = None


class VisionStepInput(BaseModel):
    scenario: Literal["plaza_normal", "bottleneck", "counterflow", "surge_gate"] = "plaza_normal"
    mode: Literal["gaussian", "point", "zone", "movement"] = "gaussian"
    sigma: float = Field(28.0, ge=5, le=80)
    steps: int = Field(1, ge=1, le=10, description="Simulation steps to advance before rendering")
    include_views: bool = True
    reset: bool = False


class CalibrationInput(BaseModel):
    source_points: dict[str, dict[str, float]]
    target_width_px: int = Field(800, ge=100, le=4096)
    target_height_px: int = Field(600, ge=100, le=4096)
    ground_width_meters: float = Field(24.0, gt=0.1, le=1000)
    ground_height_meters: float = Field(18.0, gt=0.1, le=1000)
    venue_name: str = Field("Operator calibrated area", max_length=120)


class ExplainInput(BaseModel):
    tick: int | None = Field(None, ge=0)
    snapshot: dict[str, Any] | None = None
    audience: Literal["analyst", "executive", "public"] = "executive"


class IncidentOpenInput(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    zone_id: str | None = None
    severity: Literal["low", "medium", "high", "critical"] = "high"
    source: Literal["live", "simulation", "video", "manual"] = "live"
    alert_id: str | None = Field(None, max_length=128)
    evidence: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(None, max_length=2000)


class IncidentUpdateInput(BaseModel):
    incident_id: str
    action: Literal["acknowledge", "respond", "monitor", "resolve", "close", "note"]
    note: str | None = Field(None, max_length=2000)


class IncidentRef(BaseModel):
    incident_id: str


class IncidentListInput(BaseModel):
    status: str | None = None
    limit: int = Field(100, ge=1, le=500)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event_hash(prev: str, body: dict[str, Any]) -> str:
    return _sha(prev + canonical_json(body))


class CrowdEngine(BaseEngine):
    name = "crowd"
    title = "Crowd Safety Engine (CROWDGUARD)"
    description = ("Person detection and tracking, zone occupancy with uncertainty, crowd flow, congestion alerts, "
                   "short-horizon forecasting, safety-weighted routing (NetworkX) and incident evidence.")

    def __init__(self, store=None, settings=None) -> None:
        super().__init__()
        self.store = store
        self.settings = settings
        self.venue: Venue = load_venue()
        self.planner = RouteOptimizer(self.venue)
        self._sim_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._sim_lock = threading.Lock()
        # VCIE state: the live synthetic pipeline and the operator calibration used for new video jobs.
        self._vision = None
        self._vision_lock = threading.Lock()
        self.vision_calibration = None
        self.vision_calibration_source = "default preset"

    # ---- helpers -------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        h = super().health()
        weights, _ = find_weights(getattr(self.settings, "crowd_yolo_weights", None))
        h.update({"venue": self.venue.id, "zones": len(self.venue.zones.zones),
                  "yolo_weights_found": bool(weights), "detector_preference": getattr(self.settings, "crowd_detector", "auto")})
        if not weights:
            h["warning"] = "No local YOLO weights found; video analysis will use the OpenCV HOG fallback detector."
        return h

    def _evaluator(self, ctx: ExecutionContext) -> Evaluator:
        if self.registry is None or self.registry.get("decision") is None:
            return local_evaluator()

        def evaluate(rules, facts):
            resp = self.call("decision", "evaluate_rules", {"rules": rules, "facts": facts, "default_outcome": "ok"},
                             ctx.child(actor_type="system"))
            if not resp.success:
                raise EngineError("RULES_FAILED", f"Alert rule evaluation failed: {resp.error.message if resp.error else '?'}", 500)
            return resp.result["results"]
        return evaluate

    def scenario(self, data: SimulateInput, ctx: ExecutionContext) -> dict[str, Any]:
        cfg = ScenarioConfig(seed=data.seed, intervention=data.intervention, exit_blockage=data.exit_blockage,
                             feed_outage=data.feed_outage, detector_glitch=data.detector_glitch)
        key = canonical_json(asdict(cfg))
        with self._sim_lock:
            if key in self._sim_cache:
                self._sim_cache.move_to_end(key)
                return self._sim_cache[key]
        result = run_scenario(self.venue, cfg, self._evaluator(ctx))
        with self._sim_lock:
            self._sim_cache[key] = result
            while len(self._sim_cache) > 6:
                self._sim_cache.popitem(last=False)
        return result

    def _frame(self, tick: int | None, ctx: ExecutionContext) -> tuple[dict[str, Any], dict[str, Any]]:
        sim = self.scenario(SimulateInput(), ctx)
        frames = sim["frames"]
        t = len(frames) - 1 if tick is None else min(tick, len(frames) - 1)
        return frames[t], sim

    # ---- operations ----------------------------------------------------------
    @operation("venue", EmptyInput, description="Venue model: zones, graph nodes/edges, thresholds, camera layouts")
    def op_venue(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result=self.venue.describe(), metadata={"synthetic_venue": self.venue.synthetic})

    @operation("status", EmptyInput, description="Verified capabilities: detector backend and weights, tracker, routing, AI provider")
    def op_status(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        det, det_status = get_detector(getattr(self.settings, "crowd_detector", "auto"), getattr(self.settings, "crowd_yolo_weights", None))
        try:
            from app.crowdguard.crowd_tracking import build_tracker  # noqa: PLC0415

            _, tr = build_tracker("auto")
        except Exception as exc:  # noqa: BLE001
            tr = {"tracker": "unavailable", "available": False, "reason": str(exc)}
        ai = None
        if self.registry is not None and self.registry.get("ai") is not None:
            resp = self.call("ai", "providers", {}, ctx.child(actor_type="system"))
            ai = resp.result if resp.success else {"error": resp.error.message if resp.error else "?"}
        import networkx as nx  # noqa: PLC0415

        return OpResult(result={
            "detector": det_status, "tracker": tr, "routing": {"library": "networkx", "version": nx.__version__},
            "ai": ai, "venue": {"id": self.venue.id, "name": self.venue.name, "synthetic": self.venue.synthetic},
            "limits": {"max_video_mb": getattr(self.settings, "crowd_max_video_mb", 100), "max_seconds": 120},
            "safety": DISCLAIMER,
        })

    @operation("simulate", SimulateInput, description="Deterministic synthetic event timeline with alerts, forecasts, routes and incidents")
    def op_simulate(self, data: SimulateInput, ctx: ExecutionContext) -> OpResult:
        sim = self.scenario(data, ctx)
        warn = ["All values are SYNTHETIC (deterministic simulation), not real crowd data."]
        if data.tick is None:
            return OpResult(result=sim, warnings=warn, metadata={"frames": len(sim["frames"]), "seed": data.seed})
        frames = sim["frames"]
        t = min(data.tick, len(frames) - 1)
        history = {z.id: [f["readings"][z.id]["estimate"] for f in frames[: t + 1]] for z in self.venue.zones.zones}
        return OpResult(result={"scenario": sim["scenario"], "frame": frames[t], "history": history,
                                "evaluation": sim["evaluation"], "incidents": sim["incidents"]}, warnings=warn,
                        metadata={"tick": t, "seed": data.seed})

    @operation("assess", AssessInput, description="Assess live observations: occupancy with uncertainty, alerts, forecasts and recommendations")
    def op_assess(self, data: AssessInput, ctx: ExecutionContext) -> OpResult:
        venue = self.venue
        by_zone = {o.zone_id: o for o in data.observations}
        unknown = [z for z in by_zone if venue.zones.get(z) is None]
        if unknown:
            raise EngineError("UNKNOWN_ZONE", f"Unknown zone(s): {', '.join(unknown)}", 422)
        readings, history, pct_hist, flows = {}, {}, {}, {}
        for z in venue.zones.zones:
            o = by_zone.get(z.id)
            if o is None:  # no camera reported: unknown, NOT empty
                obs = Observation(zone_id=z.id, t=data.t, feed_status="missing", source="manual", value_kind="measured")
            else:
                obs = Observation(zone_id=z.id, t=data.t, feed_status=o.feed_status,
                                  observed_count=o.observed_count if o.feed_status == "ok" else None,
                                  detector_confidence=o.detector_confidence, tracking_stability=o.tracking_stability,
                                  source=o.source, value_kind="measured", coverage=o.coverage)
            prev_hist = [v for v in data.history.get(z.id, []) if v is not None]
            prev = None
            if prev_hist and (o is None or o.feed_status != "ok"):
                prev = {"t": data.t - (o.age_s if o and o.age_s else 60.0), "estimate": int(prev_hist[-1]),
                        "lower": int(prev_hist[-1] * 0.9), "upper": int(prev_hist[-1] * 1.1), "confidence": 0.6, "age_s": 0.0}
            r = assess_reading(z, obs, prev, venue.thresholds)
            readings[z.id] = r
            history[z.id] = list(data.history.get(z.id, [])) + ([r["estimate"]] if r["feed_status"] == "ok" else [])
            pct_hist[z.id] = [v / z.safe_capacity * 100 if v is not None else None for v in history[z.id]]
            flows[z.id] = {}
        exit_status = {x["id"]: data.exit_status.get(x["id"], "open") for x in venue.exits()}
        snap = analyse_snapshot(venue, t=data.t, readings=readings, history=history, pct_history=pct_hist, flows=flows,
                                edge_flows=data.edge_flows, exit_status=exit_status, evaluator=self._evaluator(ctx))
        missing = [z for z, r in readings.items() if r["feed_status"] != "ok"]
        warnings = []
        if missing:
            warnings.append(f"{len(missing)} zone(s) have no live observation and are reported as unknown (not empty)")
        return OpResult(result=snap, warnings=warnings)

    @operation("route", RouteInput, description="Safety-weighted alternative routes with explanations (NetworkX)")
    def op_route(self, data: RouteInput, ctx: ExecutionContext) -> OpResult:
        if data.source not in self.venue.nodes:
            raise EngineError("UNKNOWN_NODE", f"Unknown source '{data.source}'", 422)
        bad = [n for n in data.blocked_nodes if n not in self.venue.nodes] + [e for e in data.blocked_edges if e not in self.venue.edges]
        if bad:
            raise EngineError("UNKNOWN_ELEMENT", f"Unknown node/edge id(s): {', '.join(bad)}", 422)
        if data.zones is not None:
            zones, util, blocked = data.zones, data.edge_utilisation or {}, set()
            tick_used = None
        else:
            frame, _ = self._frame(data.tick, ctx)
            zones = frame["readings"]
            util = {e["id"]: e["utilisation"] for e in frame["edge_flows"]}
            util.update(data.edge_utilisation or {})
            blocked = {x for x, s in frame["exit_status"].items() if s == "blocked"}
            tick_used = frame["tick"]
        state = RouteState(zones=zones, edge_utilisation=util, blocked_edges=set(data.blocked_edges),
                           blocked_nodes=blocked | set(data.blocked_nodes))
        plan = self.planner.plan(state, data.source, data.purpose, data.group_size, k=data.k)
        plan["conditions_from_tick"] = tick_used
        return OpResult(result=plan, metadata={"method": "Dijkstra on safety-weighted graph + Yen k-shortest simple paths"})

    @operation("forecast", ForecastInput, description="Zone occupancy forecast: deterministic method, ML-engine backtested forecast and rolling evaluation")
    def op_forecast(self, data: ForecastInput, ctx: ExecutionContext) -> OpResult:
        zone = self.venue.zones.get(data.zone_id)
        if zone is None:
            raise EngineError("UNKNOWN_ZONE", f"Unknown zone '{data.zone_id}'", 422)
        warnings: list[str] = []
        if data.history is not None:
            hist = [float(v) for v in data.history]
            source = "provided"
        else:
            frame, sim = self._frame(data.tick, ctx)
            hist = [f["readings"][zone.id]["estimate"] for f in sim["frames"][: frame["tick"] + 1]]
            hist = [float(v) for v in hist if v is not None]
            source = f"synthetic simulation up to tick {frame['tick']}"
            warnings.append("History is SYNTHETIC (simulation).")
        det = forecast_zone(hist, zone.safe_capacity, horizon=data.horizon)
        ml = None
        if data.use_ml and len(hist) >= 16 and self.registry is not None:
            resp = self.call("ml", "forecast", {"values": hist, "horizon": data.horizon}, ctx.child(actor_type="system"))
            if resp.success:
                r = resp.result
                ml = {**r, "peak_pct": round(max(r["forecast"]) / zone.safe_capacity * 100, 1),
                      "minutes_to_capacity": next((i + 1 for i, v in enumerate(r["forecast"]) if v >= zone.safe_capacity), None),
                      "interval_note": resp.metadata.get("interval_note")}
            else:
                warnings.append(f"ML engine forecast unavailable: {resp.error.message if resp.error else '?'}")
        elif data.use_ml:
            warnings.append(f"Only {len(hist)} points: ML forecast needs ≥ 16, so the deterministic fallback is used alone.")
        bt = rolling_backtest(hist, zone.safe_capacity, horizon=min(10, data.horizon)) if len(hist) >= 20 else {
            "available": False, "reason": "needs ≥ 20 points"}
        return OpResult(result={"zone_id": zone.id, "zone_name": zone.name, "capacity": zone.safe_capacity, "history": hist,
                                "history_source": source, "deterministic": det, "ml_engine": ml, "rolling_backtest": bt},
                        warnings=warnings)

    @operation("analyse_media", MediaInput, description="Detect, track and count people per camera zone in an uploaded image or video")
    def op_analyse_media(self, data: MediaInput, ctx: ExecutionContext) -> OpResult:
        if self.store is None:
            raise EngineError("NO_STORE", "Document storage is not configured", 503)
        doc = self.store.get_document(data.document_id)
        if doc is None:
            raise EngineError("DOCUMENT_NOT_FOUND", f"Unknown document '{data.document_id}'", 404)
        if doc["kind"] not in ("image", "video"):
            raise EngineError("NOT_MEDIA", "Document is not an image or video", 422)
        layouts = self.venue.cfg.get("camera_layouts", {})
        layout = data.custom_layout or layouts.get(data.layout or "")
        if not layout:
            raise EngineError("UNKNOWN_LAYOUT", f"Unknown camera layout '{data.layout}'", 422)
        layout = {**layout, "zones": [dict(z) for z in layout["zones"]]}
        if data.venue_zone:
            if self.venue.zones.get(data.venue_zone) is None:
                raise EngineError("UNKNOWN_ZONE", f"Unknown venue zone '{data.venue_zone}'", 422)
            for z in layout["zones"]:
                z["venue_zone"] = data.venue_zone
                if data.coverage:
                    z["coverage"] = data.coverage / len(layout["zones"])
        path = Path(doc["storage_path"])
        if not path.is_file():
            raise EngineError("FILE_MISSING", "Stored media file is missing", 410)
        def progress(done: int, total: int) -> None:
            if data.job_id:
                MEDIA_PROGRESS.setdefault(data.job_id, {}).update(done=done, total=total)

        calib = self.vision_calibration if self.vision_calibration_source == "operator calibrated" else None
        try:
            res = analyse_media(path, doc["kind"], layout, calibration=calib,
                                calibration_source="operator calibrated" if calib else "default preset",
                                max_seconds=data.max_seconds, target_fps=data.target_fps, thresholds=self.venue.thresholds,
                                heatmap_mode=data.heatmap_mode, sigma=data.sigma, progress=progress)
        except ValueError as exc:
            raise EngineError("INVALID_LAYOUT", str(exc), 422) from exc
        if not res.get("ok"):
            raise EngineError(res.get("error", "MEDIA_FAILED").upper(), res.get("message", "Media analysis failed"), 422)
        res["document"] = {"id": doc["id"], "filename": doc["filename"], "sha256": doc["sha256"], "kind": doc["kind"], "size": doc["size"]}
        # Map camera zones onto venue zones (sum counts; coverage-based extrapolation is labelled as such).
        venue_obs: dict[str, dict[str, Any]] = {}
        for z, o in zip(layout["zones"], res["observations"]):
            vz = z.get("venue_zone")
            if not vz:
                continue
            agg = venue_obs.setdefault(vz, {"zone_id": vz, "observed_count": 0, "feed_status": "ok", "coverage": 0.0,
                                            "detector_confidence": o["detector_confidence"], "tracking_stability": o["tracking_stability"],
                                            "source": doc["kind"]})
            if o["feed_status"] != "ok" or o["observed_count"] is None:
                agg["feed_status"] = "detector_error"
            else:
                agg["observed_count"] += o["observed_count"]
            agg["coverage"] = min(1.0, agg["coverage"] + float(z.get("coverage") or 0.0))
        for v in venue_obs.values():
            if not v["coverage"]:
                v["coverage"] = 1.0
        res["venue_observations"] = list(venue_obs.values())
        return OpResult(result=res, warnings=res["warnings"][:10],
                        confidence=None, metadata={"detector": res["detector"].get("backend"), "tracker": res["tracker"].get("tracker"),
                                                   "source_kind": res["source_kind"]})

    @operation("explain", ExplainInput, description="Plain-language situation briefing via the AI engine (LLM or labelled local fallback)")
    def op_explain(self, data: ExplainInput, ctx: ExecutionContext) -> OpResult:
        if data.snapshot is not None:
            snap, label = data.snapshot, "provided snapshot"
        else:
            snap, _ = self._frame(data.tick, ctx)
            label = f"synthetic simulation at {snap.get('clock')}"
        context = {
            "data_label": label,
            "summary": snap.get("summary"),
            "top_alerts": [a.get("message") for a in (snap.get("alerts") or [])[:6]],
            "top_recommendations": [{"action": r.get("title"), "why": (r.get("rationale") or [])[:2]} for r in (snap.get("recommendations") or [])[:4]],
            "zones": {zid: {"occupancy_pct": r.get("occupancy_pct"), "band": r.get("band"), "feed": r.get("feed_status")}
                      for zid, r in (snap.get("readings") or {}).items()},
            "rule": "Advisory only; human organisers decide; emergency exits are never closed by software.",
        }
        if self.registry is None:
            raise EngineError("NOT_INITIALISED", "Registry unavailable", 500)
        resp = self.call("ai", "explain", {"subject": "crowd safety situation", "context": context, "audience": data.audience,
                                           "max_words": 140}, ctx.child(actor_type="system"))
        if not resp.success:
            raise EngineError("EXPLAIN_FAILED", resp.error.message if resp.error else "explanation failed", resp._status)
        return OpResult(result={"explanation": resp.result["explanation"], "context": context}, warnings=resp.warnings,
                        metadata={k: resp.metadata.get(k) for k in ("provider", "model", "fallback", "fallback_reason")})

    # ---- Virtual Crowd Intelligence Engine (VCIE) -----------------------------
    def vision_pipeline(self):
        """The live synthetic VCIE pipeline (created lazily, shared, guarded by its own lock)."""
        with self._vision_lock:
            if self._vision is None:
                from app.crowdguard.pipeline import VirtualCrowdIntelligencePipeline  # noqa: PLC0415

                self._vision = VirtualCrowdIntelligencePipeline(self.vision_calibration, identity_tracking=False)
                self._vision.step_synthetic(scenario="plaza_normal")
            return self._vision

    @operation("vision_presets", EmptyInput, description="VCIE calibration preset, digital-twin venue, synthetic scenarios and heatmap modes")
    def op_vision_presets(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        from app.crowdguard.calibration import CameraCalibrationEngine  # noqa: PLC0415
        from app.crowdguard.schemas import HeatmapMode  # noqa: PLC0415

        p = self.vision_pipeline()
        return OpResult(result={
            "calibration": p.calibration.config.model_dump(mode="json"),
            "calibration_result": p.calibration.result.model_dump(mode="json") if p.calibration.result else None,
            "calibration_source": self.vision_calibration_source,
            "default_calibration": CameraCalibrationEngine.get_default_calibration().model_dump(mode="json"),
            "venue": p.venue.model.model_dump(mode="json"),
            "scenarios": [
                {"id": "plaza_normal", "name": "Plaza multi-directional flow", "description": "35 synthetic pedestrians crossing an open concourse."},
                {"id": "bottleneck", "name": "Corridor bottleneck", "description": "45 synthetic pedestrians funnelling through a narrow exit."},
                {"id": "counterflow", "name": "Opposing streams", "description": "Two synthetic groups meeting head-on (counter-flow)."},
                {"id": "surge_gate", "name": "Ingress gate surge", "description": "60 synthetic pedestrians converging on the north gate."},
            ],
            "heatmap_modes": [m.value for m in HeatmapMode],
            "detector": p.detector.describe(),
        })

    @operation("vision_calibrate", CalibrationInput, access="write", description="Validate a four-point ground-plane homography and use it for the VCIE")
    def op_vision_calibrate(self, data: CalibrationInput, ctx: ExecutionContext) -> OpResult:
        from app.crowdguard.schemas import CalibrationConfig  # noqa: PLC0415

        try:
            cfg = CalibrationConfig.model_validate(data.model_dump())
        except Exception as exc:  # noqa: BLE001
            raise EngineError("INVALID_CALIBRATION", f"Calibration points are malformed: {exc}", 422) from exc
        p = self.vision_pipeline()
        with p.lock:
            result = p.calibration.calibrate(cfg)
            if not result.valid:
                raise EngineError("INVALID_CALIBRATION", result.message, 422, details={"warnings": result.warnings})
            for eng in (p.perspective, p.detector, p.tracker, p.density_engine, p.movement_engine, p.synthetic_engine):
                eng.calib = p.calibration
            p.tracker.tracks.clear()
        self.vision_calibration = cfg
        self.vision_calibration_source = "operator calibrated"
        return OpResult(result=result.model_dump(mode="json"), warnings=result.warnings,
                        metadata={"applies_to": "live synthetic view and video jobs started after this call"})

    @operation("vision_step", VisionStepInput, description="Advance the synthetic VCIE scenario and return telemetry with five synchronised views")
    def op_vision_step(self, data: VisionStepInput, ctx: ExecutionContext) -> OpResult:
        from app.crowdguard.schemas import HeatmapMode  # noqa: PLC0415

        p = self.vision_pipeline()
        with p.lock:
            p.config.heatmap_mode = HeatmapMode(data.mode)
            p.config.kde_bandwidth_sigma = data.sigma
            if data.reset or p.synthetic_engine.scenario_name != data.scenario:
                p.synthetic_engine._init_scenario(data.scenario)
                p.tracker.tracks.clear()
            res = None
            for _ in range(data.steps):
                res = p.step_synthetic(scenario=data.scenario)
            payload = res.model_dump(mode="json")
            for t in payload["tracks"]:
                t["history"] = t["history"][-12:]  # bounded payload
            views = p.render_bundle(max_width=560) if data.include_views else None
        return OpResult(result={"telemetry": payload, "views": views, "scenario": data.scenario,
                                "label": "SYNTHETIC: simulated pedestrians with ground-truth boxes (no camera, no detector)",
                                "calibration_source": self.vision_calibration_source, "fps": p.fps},
                        warnings=["Synthetic VCIE scenario: not camera data."])

    # ---- incidents -------------------------------------------------------------
    def _need_store(self):
        if self.store is None:
            raise EngineError("NO_STORE", "Incident storage is not configured", 503)
        return self.store

    def _hash_evidence(self, evidence: dict[str, Any], ctx: ExecutionContext) -> str:
        text = canonical_json(evidence)
        if self.registry is not None and self.registry.get("crypto") is not None:
            resp = self.call("crypto", "hash", {"text": text}, ctx.child(actor_type="system"))
            if resp.success:
                return resp.result["digest"]
        return _sha(text)

    @operation("incident_open", IncidentOpenInput, access="write", description="Open an incident with a sealed evidence snapshot")
    def op_incident_open(self, data: IncidentOpenInput, ctx: ExecutionContext) -> OpResult:
        store = self._need_store()
        evidence = {**data.evidence, "captured_at": utcnow_iso(), "source": data.source}
        ev_hash = self._hash_evidence(evidence, ctx)
        body = {"seq": 0, "ts": utcnow_iso(), "status": "detected", "action": "open", "actor": ctx.actor,
                "role": ctx.role, "note": data.note or data.title}
        event = {**body, "prev_hash": ev_hash, "hash": _event_hash(ev_hash, body)}
        inc = store.add_incident(id="INC-" + uuid.uuid4().hex[:8].upper(), title=data.title, zone_id=data.zone_id,
                                 severity=data.severity, status="detected", source=data.source, alert_id=data.alert_id,
                                 evidence=evidence, evidence_hash=ev_hash, events=[event], created_by=ctx.actor)
        store.audit("incident", "incident_opened", actor=ctx.actor, role=ctx.role,
                    severity="warning" if data.severity in ("high", "critical") else "info",
                    detail={"incident_id": inc["id"], "zone": data.zone_id, "severity": data.severity, "evidence_hash": ev_hash})
        return OpResult(result=inc)

    @operation("incident_update", IncidentUpdateInput, access="write", description="Advance an incident's lifecycle (human actors only)")
    def op_incident_update(self, data: IncidentUpdateInput, ctx: ExecutionContext) -> OpResult:
        store = self._need_store()
        inc = store.get_incident(data.incident_id)
        if inc is None:
            raise EngineError("INCIDENT_NOT_FOUND", f"Unknown incident '{data.incident_id}'", 404)
        if ctx.actor_type != "human":
            raise EngineError("HUMAN_REQUIRED", "Incident decisions must be made by a human organiser", 403)
        allowed, new_status = INCIDENT_FLOW[data.action]
        if inc["status"] not in allowed:
            raise EngineError("INVALID_TRANSITION", f"Cannot '{data.action}' an incident that is '{inc['status']}'", 409,
                              details={"allowed_from": sorted(allowed)})
        if data.action == "close" and ctx.actor == inc["created_by"]:
            store.audit("incident", "self_close_blocked", actor=ctx.actor, role=ctx.role, severity="warning",
                        detail={"incident_id": inc["id"]})
            raise EngineError("FOUR_EYES", "The person who opened an incident cannot also close it", 403)
        events = list(inc["events"])
        prev = events[-1]["hash"] if events else inc["evidence_hash"]
        body = {"seq": len(events), "ts": utcnow_iso(), "status": new_status or inc["status"], "action": data.action,
                "actor": ctx.actor, "role": ctx.role, "note": data.note or ""}
        events.append({**body, "prev_hash": prev, "hash": _event_hash(prev, body)})
        fields: dict[str, Any] = {"events": events, "status": new_status or inc["status"], "updated_at": utcnow_iso()}
        if data.action == "close":
            leaves = [inc["evidence_hash"]] + [e["hash"] for e in events]
            root = None
            if self.registry is not None:
                resp = self.call("crypto", "merkle_root", {"leaves": leaves, "leaf_encoding": "sha256_hex"},
                                 ctx.child(actor_type="system"))
                root = resp.result.get("root") if resp.success else None
            fields["sealed_root"] = root
        out = store.update_incident(inc["id"], **fields)
        store.audit("incident", f"incident_{data.action}", actor=ctx.actor, role=ctx.role,
                    detail={"incident_id": inc["id"], "status": out["status"], "event_hash": events[-1]["hash"],
                            "sealed_root": out.get("sealed_root")})
        return OpResult(result=out)

    @operation("incident_list", IncidentListInput, description="List incidents")
    def op_incident_list(self, data: IncidentListInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result={"incidents": self._need_store().list_incidents(status=data.status, limit=data.limit)})

    @operation("incident_verify", IncidentRef, description="Recompute an incident's evidence hash, event chain and seal")
    def op_incident_verify(self, data: IncidentRef, ctx: ExecutionContext) -> OpResult:
        inc = self._need_store().get_incident(data.incident_id)
        if inc is None:
            raise EngineError("INCIDENT_NOT_FOUND", f"Unknown incident '{data.incident_id}'", 404)
        checks = []
        ev_ok = _sha(canonical_json(inc["evidence"])) == inc["evidence_hash"]
        checks.append({"check": "evidence snapshot hash", "passed": ev_ok})
        prev = inc["evidence_hash"]
        chain_ok, broken_at = True, None
        for e in inc["events"]:
            body = {k: e[k] for k in ("seq", "ts", "status", "action", "actor", "role", "note")}
            if e["prev_hash"] != prev or e["hash"] != _event_hash(prev, body):
                chain_ok, broken_at = False, e["seq"]
                break
            prev = e["hash"]
        checks.append({"check": "event hash chain", "passed": chain_ok, "broken_at_seq": broken_at})
        if inc.get("sealed_root"):
            leaves = [inc["evidence_hash"]] + [e["hash"] for e in inc["events"]]  # closed incidents accept no further events
            resp = self.call("crypto", "merkle_root", {"leaves": leaves, "leaf_encoding": "sha256_hex"},
                             ctx.child(actor_type="system")) if self.registry else None
            root = resp.result.get("root") if resp and resp.success else None
            checks.append({"check": "sealed Merkle root", "passed": root == inc["sealed_root"], "root": root})
        return OpResult(result={"incident_id": inc["id"], "valid": all(c["passed"] for c in checks), "checks": checks,
                                "events": len(inc["events"]), "head": prev})
