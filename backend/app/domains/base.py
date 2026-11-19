"""Domain adapters and the generic pipeline runner.

A domain adapter is configuration, not an application: it names the engines it
needs, the UI sections to show, an input model, sample data, and an ordered
list of `Step`s. Each step builds an engine payload from the context of earlier
steps; the runner executes it through the registry (so policy, validation and
audit apply uniformly) and records per-step status for the UI.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.core.contracts import ExecutionContext
from app.core.registry import EngineRegistry
from app.db.models import utcnow_iso

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample_data"
ALL_SECTIONS = ["overview", "workspace", "ingestion", "runs", "analytics", "approvals", "engines", "audit", "settings"]


class PipelineContext:
    def __init__(self, data: dict[str, Any], run_id: str) -> None:
        self.input = data
        self.run_id = run_id
        self.results: dict[str, Any] = {}
        self.meta: dict[str, Any] = {}
        self.vars: dict[str, Any] = {}

    def r(self, step_id: str, default: Any = None) -> Any:
        return self.results.get(step_id, default)


@dataclass
class Step:
    id: str
    title: str
    engine: str
    operation: str
    build: Callable[[PipelineContext], dict[str, Any] | list[dict[str, Any]] | None]
    why: str = ""
    foreach: bool = False   # build returns a list of payloads, one execution each
    optional: bool = False  # failure does not abort the run


@dataclass
class DomainAdapter:
    id: str
    name: str
    tagline: str
    description: str
    icon: str
    color: str
    scenario: str
    input_model: type[BaseModel]
    steps: list[Step]
    present: Callable[[PipelineContext], dict[str, Any]]
    sections: list[str] = field(default_factory=lambda: list(ALL_SECTIONS))
    sample_file: str | None = None
    impact: str = ""

    @property
    def engines(self) -> list[str]:
        return list(dict.fromkeys(s.engine for s in self.steps))

    def sample(self) -> dict[str, Any]:
        if not self.sample_file:
            return {}
        return json.loads((SAMPLE_DIR / self.sample_file).read_text(encoding="utf-8"))

    def describe(self, with_sample: bool = False) -> dict[str, Any]:
        out = {
            "id": self.id, "name": self.name, "tagline": self.tagline, "description": self.description,
            "icon": self.icon, "color": self.color, "scenario": self.scenario, "impact": self.impact,
            "engines": self.engines, "sections": self.sections,
            "steps": [{"id": s.id, "title": s.title, "engine": s.engine, "operation": s.operation, "why": s.why,
                       "foreach": s.foreach, "optional": s.optional} for s in self.steps],
            "input_schema": self.input_model.model_json_schema(),
        }
        if with_sample:
            out["sample_input"] = self.sample()
        return out


def run_pipeline(adapter: DomainAdapter, raw_input: dict[str, Any] | None, registry: EngineRegistry,
                 store, ctx: ExecutionContext) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:16]
    started = time.perf_counter()
    created = utcnow_iso()
    ctx = ctx.child(run_id=run_id)
    data = raw_input if raw_input else adapter.sample()
    record: dict[str, Any] = {"id": run_id, "domain": adapter.id, "status": "running", "actor": ctx.actor,
                              "role": ctx.role, "input": data, "steps": [], "presentation": None, "error": None,
                              "created_at": created}
    try:
        validated = adapter.input_model.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        record.update(status="failed", error="Input validation failed: " + "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10]))
        return _finish(record, started, store, ctx)

    pc = PipelineContext(validated, run_id)
    for step in adapter.steps:
        step_rec: dict[str, Any] = {"id": step.id, "title": step.title, "engine": step.engine,
                                    "operation": step.operation, "why": step.why, "status": "running",
                                    "warnings": [], "items": 0, "execution_time_ms": 0.0}
        t0 = time.perf_counter()
        try:
            built = step.build(pc)
        except Exception as exc:  # noqa: BLE001 - surface adapter bugs as a failed step
            built, step_rec["status"], step_rec["error"] = None, "failed", f"Could not build step input: {type(exc).__name__}: {exc}"
        if step_rec["status"] != "failed":
            if built is None or (step.foreach and not built):
                step_rec["status"] = "skipped"
            else:
                payloads = built if step.foreach else [built]
                responses = [registry.execute(step.engine, step.operation, p, ctx) for p in payloads]
                ok = all(r.success for r in responses)
                step_rec["items"] = len(responses)
                step_rec["status"] = "completed" if ok else "failed"
                step_rec["warnings"] = list(dict.fromkeys(w for r in responses for w in r.warnings))[:10]
                errors = [f"{r.error.code}: {r.error.message}" for r in responses if r.error]
                if errors:
                    step_rec["error"] = "; ".join(dict.fromkeys(errors))[:1000]
                if not step.foreach:
                    step_rec["confidence"] = responses[0].confidence
                    step_rec["metadata"] = responses[0].metadata
                    pc.meta[step.id] = responses[0].metadata
                    pc.results[step.id] = responses[0].result if responses[0].success else None
                else:
                    pc.results[step.id] = [r.result if r.success else None for r in responses]
                    pc.meta[step.id] = [r.metadata for r in responses]
                step_rec["result"] = pc.results[step.id]
        step_rec["execution_time_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        record["steps"].append(step_rec)
        if step_rec["status"] == "failed" and not step.optional:
            record.update(status="failed", error=f"Step '{step.title}' failed: {step_rec.get('error')}")
            break

    if record["status"] == "running":
        try:
            record["presentation"] = adapter.present(pc)
            record["status"] = "completed"
        except Exception as exc:  # noqa: BLE001
            record.update(status="failed", error=f"Result presentation failed: {type(exc).__name__}: {exc}")
    return _finish(record, started, store, ctx)


def _finish(record: dict[str, Any], started: float, store, ctx: ExecutionContext) -> dict[str, Any]:
    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    record["finished_at"] = utcnow_iso()
    if store is not None:
        store.save_run(record)
        store.audit("pipeline", f"run_{record['status']}", actor=ctx.actor, role=ctx.role,
                    severity="info" if record["status"] == "completed" else "warning",
                    detail={"run_id": record["id"], "domain": record["domain"], "duration_ms": record["duration_ms"],
                            "error": record["error"]})
    return record


# ------------------------------------------------------------------ presentation helpers
def metric(label: str, value: Any, tone: str = "neutral", hint: str | None = None) -> dict[str, Any]:
    return {"label": label, "value": value, "tone": tone, "hint": hint}


def chart(kind: str, title: str, data: list[dict], x: str, series: list[tuple[str, str]], **extra: Any) -> dict[str, Any]:
    return {"type": kind, "title": title, "data": data, "x": x,
            "series": [{"key": k, "label": label} for k, label in series], **extra}


def table(title: str, columns: list[tuple[str, str]], rows: list[dict], **extra: Any) -> dict[str, Any]:
    return {"title": title, "columns": [{"key": k, "label": label} for k, label in columns], "rows": rows, **extra}


def tone_for_band(band: str | None) -> str:
    return {"critical": "bad", "high": "bad", "medium": "warn", "low": "good"}.get(band or "", "neutral")


def narrative_of(pc: PipelineContext, step_id: str, key: str) -> dict[str, Any] | None:
    res = pc.r(step_id)
    if not res or not res.get(key):
        return None
    meta = pc.meta.get(step_id) or {}
    return {"text": res[key], "source": meta.get("provider", "unknown"), "model": meta.get("model"),
            "fallback": bool(meta.get("fallback"))}
