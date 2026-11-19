"""Decision engine: declarative rules, weighted risk scoring, multi-signal
aggregation with a transparent confidence heuristic, and human approvals.

No `eval` is used anywhere: rule conditions are a small JSON DSL interpreted
by `_evaluate`.
"""
from __future__ import annotations

import re
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation
from app.db.models import utcnow_iso

Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "not_contains", "exists", "regex", "between"]
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class Condition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    field: str | None = None
    op: Op | None = None
    value: Any = None
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    not_: "Condition | None" = Field(None, alias="not")

    @model_validator(mode="after")
    def _shape(self):
        kinds = sum(x is not None for x in (self.all, self.any, self.not_)) + (1 if self.field else 0)
        if kinds != 1:
            raise ValueError("A condition must be exactly one of: {field, op, value}, all, any, not")
        if self.field and not self.op:
            raise ValueError("'op' is required with 'field'")
        return self


class Rule(BaseModel):
    id: str = Field(..., max_length=100)
    description: str = ""
    when: Condition
    outcome: str = Field("flag", max_length=100)
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    weight: float = Field(1.0, ge=0)


class RulesInput(BaseModel):
    rules: list[Rule] = Field(..., min_length=1, max_length=500)
    facts: dict[str, Any] | list[dict[str, Any]] = Field(..., description="One fact object or a list (batch)")
    default_outcome: str = "pass"


class Factor(BaseModel):
    name: str
    value: float
    min: float = 0.0
    max: float = 1.0
    weight: float = Field(1.0, ge=0)
    invert: bool = Field(False, description="Higher raw value means lower risk")


class RiskItem(BaseModel):
    id: str | int | None = None
    factors: list[Factor] = Field(..., min_length=1)


class RiskInput(BaseModel):
    factors: list[Factor] | None = None
    items: list[RiskItem] | None = Field(None, description="Batch mode")
    thresholds: dict[str, float] = Field(default_factory=lambda: {"medium": 25, "high": 55, "critical": 80})

    @model_validator(mode="after")
    def _one(self):
        if (self.factors is None) == (self.items is None):
            raise ValueError("Provide exactly one of 'factors' or 'items'")
        return self


class Signal(BaseModel):
    source: str
    score: float = Field(..., ge=0, le=1)
    weight: float = Field(1.0, ge=0)
    confidence: float | None = Field(None, ge=0, le=1, description="Source's own confidence, if it has one")


class AggregateItem(BaseModel):
    id: str | int | None = None
    signals: list[Signal] = Field(..., min_length=1)


class AggregateInput(BaseModel):
    signals: list[Signal] | None = None
    items: list[AggregateItem] | None = None
    method: Literal["weighted_mean", "max", "noisy_or"] = "weighted_mean"
    expected_sources: int | None = Field(None, ge=1, description="For coverage: how many signals should be present")
    decision_threshold: float = Field(0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _one(self):
        if (self.signals is None) == (self.items is None):
            raise ValueError("Provide exactly one of 'signals' or 'items'")
        return self


class ApprovalRequestInput(BaseModel):
    title: str = Field(..., max_length=255)
    action: str = Field(..., max_length=128, description="The action awaiting approval, e.g. 'hold_transaction'")
    payload: dict[str, Any] = Field(default_factory=dict)
    risk_score: float | None = None
    run_id: str | None = None


class ApprovalDecisionInput(BaseModel):
    approval_id: str
    decision: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=2000)


class ApprovalListInput(BaseModel):
    status: Literal["pending", "approved", "rejected"] | None = None
    limit: int = Field(100, ge=1, le=500)


def _get(facts: dict[str, Any], path: str) -> tuple[bool, Any]:
    cur: Any = facts
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _evaluate(cond: Condition, facts: dict[str, Any]) -> bool:
    if cond.all is not None:
        return all(_evaluate(c, facts) for c in cond.all)
    if cond.any is not None:
        return any(_evaluate(c, facts) for c in cond.any)
    if cond.not_ is not None:
        return not _evaluate(cond.not_, facts)
    present, v = _get(facts, cond.field or "")
    op, ref = cond.op, cond.value
    if op == "exists":
        return present == bool(ref if ref is not None else True)
    if not present or v is None:
        return False
    try:
        if op == "eq":
            return v == ref
        if op == "ne":
            return v != ref
        if op in ("gt", "gte", "lt", "lte"):
            a, b = float(v), float(ref)
            return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
        if op == "between":
            lo, hi = ref
            return float(lo) <= float(v) <= float(hi)
        if op == "in":
            return v in ref
        if op == "not_in":
            return v not in ref
        if op == "contains":
            return str(ref).lower() in str(v).lower() if isinstance(v, str) else ref in v
        if op == "not_contains":
            return str(ref).lower() not in str(v).lower() if isinstance(v, str) else ref not in v
        if op == "regex":
            return bool(re.search(str(ref)[:200], str(v)[:10_000]))
    except (TypeError, ValueError, re.error):
        return False
    return False


def _band(score: float, thresholds: dict[str, float]) -> str:
    out = "low"
    for name in ("medium", "high", "critical"):
        if name in thresholds and score >= thresholds[name]:
            out = name
    return out


def _risk(factors: list[Factor], thresholds: dict[str, float]) -> dict[str, Any]:
    total_w = sum(f.weight for f in factors) or 1.0
    contributions = []
    score = 0.0
    for f in factors:
        span = (f.max - f.min) or 1.0
        norm = min(1.0, max(0.0, (f.value - f.min) / span))
        if f.invert:
            norm = 1.0 - norm
        pts = f.weight * norm / total_w * 100
        score += pts
        contributions.append({"factor": f.name, "value": f.value, "normalised": round(norm, 4), "points": round(pts, 2)})
    contributions.sort(key=lambda c: -c["points"])
    score = round(score, 2)
    return {"score": score, "band": _band(score, thresholds), "contributions": contributions}


def _aggregate(signals: list[Signal], method: str, expected: int | None, threshold: float) -> dict[str, Any]:
    scores = np.array([s.score for s in signals])
    weights = np.array([s.weight for s in signals], dtype=float)
    if method == "max":
        combined = float(scores.max())
    elif method == "noisy_or":
        combined = float(1 - np.prod(1 - scores))
    else:
        combined = float(np.average(scores, weights=weights if weights.sum() else None))
    # Confidence heuristic: agreement between signals x coverage x mean source confidence.
    agreement = float(max(0.0, 1 - (scores.std() / 0.5))) if len(scores) > 1 else 0.5
    coverage = min(1.0, len(signals) / expected) if expected else 1.0
    src_conf = [s.confidence for s in signals if s.confidence is not None]
    source_conf = float(np.mean(src_conf)) if src_conf else 1.0
    confidence = round(agreement * coverage * source_conf, 4)
    return {"combined_score": round(combined, 4), "decision": "flag" if combined >= threshold else "clear",
            "agreement": round(agreement, 4), "coverage": round(coverage, 4), "confidence": confidence,
            "signals": [s.model_dump() for s in signals]}


class DecisionEngine(BaseEngine):
    name = "decision"
    title = "Decision Engine"
    description = "Rule evaluation, risk scoring, signal aggregation with confidence, and human approval workflows."

    def __init__(self, store=None) -> None:
        super().__init__()
        self.store = store

    def _need_store(self):
        if self.store is None:
            raise EngineError("NO_STORE", "Approval storage is not configured", 503)
        return self.store

    @operation("evaluate_rules", RulesInput, description="Evaluate declarative JSON rules against facts (single or batch)")
    def op_evaluate_rules(self, data: RulesInput, ctx: ExecutionContext) -> OpResult:
        batch = isinstance(data.facts, list)
        facts_list = data.facts if batch else [data.facts]
        total_w = sum(r.weight for r in data.rules) or 1.0
        results = []
        for facts in facts_list:
            matched = [r for r in data.rules if _evaluate(r.when, facts)]
            top = max(matched, key=lambda r: SEVERITY_RANK[r.severity], default=None)
            results.append({
                "outcome": top.outcome if top else data.default_outcome,
                "max_severity": top.severity if top else None,
                "rule_score": round(sum(r.weight for r in matched) / total_w * 100, 2),
                "matched": [{"id": r.id, "description": r.description, "outcome": r.outcome, "severity": r.severity} for r in matched],
            })
        result = {"results": results} if batch else results[0]
        return OpResult(result=result, metadata={"rules": len(data.rules), "evaluated": len(facts_list)})

    @operation("risk_score", RiskInput, description="Weighted, explainable 0-100 risk score with per-factor contributions")
    def op_risk_score(self, data: RiskInput, ctx: ExecutionContext) -> OpResult:
        if data.items is not None:
            return OpResult(result={"items": [{"id": it.id, **_risk(it.factors, data.thresholds)} for it in data.items]})
        return OpResult(result=_risk(data.factors or [], data.thresholds), metadata={"thresholds": data.thresholds})

    @operation("aggregate", AggregateInput, description="Combine model/rule signals; reports agreement-based confidence")
    def op_aggregate(self, data: AggregateInput, ctx: ExecutionContext) -> OpResult:
        meta = {"method": data.method, "confidence_formula": "agreement(1 - std/0.5) x coverage x mean(source confidence); heuristic, uncalibrated"}
        if data.items is not None:
            items = [{"id": it.id, **_aggregate(it.signals, data.method, data.expected_sources, data.decision_threshold)} for it in data.items]
            return OpResult(result={"items": items}, metadata=meta)
        out = _aggregate(data.signals or [], data.method, data.expected_sources, data.decision_threshold)
        return OpResult(result=out, confidence=out["confidence"], metadata=meta)

    @operation("request_approval", ApprovalRequestInput, access="write", description="Queue an action for human review")
    def op_request_approval(self, data: ApprovalRequestInput, ctx: ExecutionContext) -> OpResult:
        store = self._need_store()
        row = store.add_approval(title=data.title, action=data.action, payload=data.payload, risk_score=data.risk_score,
                                 status="pending", requested_by=ctx.actor, requested_role=ctx.role,
                                 requested_actor_type=ctx.actor_type, run_id=data.run_id or ctx.run_id)
        store.audit("approval", "requested", actor=ctx.actor, role=ctx.role,
                    detail={"approval_id": row["id"], "action": data.action, "risk_score": data.risk_score})
        return OpResult(result=row)

    @operation("decide_approval", ApprovalDecisionInput, access="sensitive", permission="approval:decide",
               description="Approve or reject a pending request (human reviewer; no self-approval)")
    def op_decide_approval(self, data: ApprovalDecisionInput, ctx: ExecutionContext) -> OpResult:
        store = self._need_store()
        row = store.get_approval(data.approval_id)
        if row is None:
            raise EngineError("APPROVAL_NOT_FOUND", "Unknown approval id", 404)
        if row["status"] != "pending":
            raise EngineError("ALREADY_DECIDED", f"Approval is already {row['status']}", 409)
        if ctx.actor_type != "human":
            raise EngineError("HUMAN_REQUIRED", "Only a human reviewer can decide approvals", 403)
        if ctx.actor == row["requested_by"]:
            store.audit("security", "self_approval_blocked", actor=ctx.actor, role=ctx.role, severity="warning",
                        detail={"approval_id": row["id"]})
            raise EngineError("SELF_APPROVAL", "The requester cannot approve their own request", 403)
        status = "approved" if data.decision == "approve" else "rejected"
        updated = store.update_approval(row["id"], status=status, reviewer=ctx.actor, reviewer_role=ctx.role,
                                        note=data.note, decided_at=utcnow_iso())
        store.audit("approval", status, actor=ctx.actor, role=ctx.role,
                    detail={"approval_id": row["id"], "action": row["action"], "note": data.note})
        return OpResult(result=updated or {})

    @operation("list_approvals", ApprovalListInput, description="List approval requests")
    def op_list_approvals(self, data: ApprovalListInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result={"approvals": self._need_store().list_approvals(status=data.status, limit=data.limit)})
