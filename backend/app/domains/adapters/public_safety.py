"""Public safety & emergency: call triage and dispatch prioritisation."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table, tone_for_band

LIFE_THREAT = ["not breathing", "unconscious", "trapped", "knife", "gun", "weapon", "children", "child", "collapsed",
               "bleeding", "fire spreading", "explosion", "gas"]
CATEGORY_BASE = {"fire": 1.0, "medical": 1.0, "crime": 0.8, "hazard": 0.7, "traffic": 0.6}


class Example(BaseModel):
    text: str = Field(..., min_length=3)
    category: str


class Incident(BaseModel):
    id: str
    received_at: str
    caller_text: str = Field(..., min_length=3, max_length=5_000)


class Input(BaseModel):
    training: list[Example] = Field(..., min_length=10)
    incidents: list[Incident] = Field(..., min_length=1, max_length=2_000)


RULES = [
    {"id": "life-threat", "description": "Life-threat keywords in the call", "severity": "critical", "outcome": "dispatch_immediately",
     "when": {"field": "life_threat_terms", "op": "gte", "value": 1}},
    {"id": "fire-medical", "description": "Fire or medical category", "severity": "high", "outcome": "dispatch_priority",
     "when": {"field": "category", "op": "in", "value": ["fire", "medical"]}},
    {"id": "low-confidence", "description": "Classifier unsure: human call-taker must confirm", "severity": "medium",
     "outcome": "human_triage_required", "when": {"field": "confidence", "op": "lt", "value": 0.45}},
]


def _terms(text: str) -> list[str]:
    t = text.lower()
    return [k for k in LIFE_THREAT if re.search(rf"\b{re.escape(k)}\b", t)]


def _facts(pc: PipelineContext) -> dict:
    preds = pc.r("classify")["predictions"]
    facts = [{"category": p["label"], "confidence": p["probability"], "life_threat_terms": len(_terms(i["caller_text"]))}
             for i, p in zip(pc.input["incidents"], preds)]
    return {"rules": RULES, "facts": facts, "default_outcome": "dispatch_routine"}


SEV = {None: 0, "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _priority(pc: PipelineContext) -> dict:
    items = []
    for inc, p, r in zip(pc.input["incidents"], pc.r("classify")["predictions"], pc.r("rules")["results"]):
        items.append({"id": inc["id"], "factors": [
            {"name": "rule severity", "value": SEV[r["max_severity"]], "max": 4, "weight": 3},
            {"name": "life-threat terms", "value": len(_terms(inc["caller_text"])), "max": 2, "weight": 2},
            {"name": "category base priority", "value": CATEGORY_BASE.get(p["label"], 0.5), "weight": 1},
        ]})
    return {"items": items, "thresholds": {"medium": 30, "high": 55, "critical": 80}}


def present(pc: PipelineContext) -> dict:
    incs, preds = pc.input["incidents"], pc.r("classify")["predictions"]
    rules, prio = pc.r("rules")["results"], pc.r("priority")["items"]
    ents = pc.r("entities") or [None] * len(incs)
    rows = []
    for inc, p, r, pr, e in zip(incs, preds, rules, prio, ents):
        rows.append({"id": inc["id"], "time": inc["received_at"][11:16], "call": inc["caller_text"],
                     "category": f"{p['label']} ({p['probability']:.2f})", "priority": pr["score"], "band": pr["band"],
                     "action": r["outcome"], "callback": ", ".join((e or {}).get("entities", {}).get("phone", [])) or "—"})
    rows.sort(key=lambda x: -x["priority"])
    counts: dict[str, int] = {}
    for p in preds:
        counts[p["label"]] = counts.get(p["label"], 0) + 1
    m = pc.r("classify")["metrics"]
    crit = sum(1 for r in rows if r["action"] == "dispatch_immediately")
    return {
        "headline": f"{len(rows)} calls triaged: {crit} need immediate dispatch; top priority {rows[0]['id']}",
        "metrics": [
            metric("Immediate dispatch", crit, "bad" if crit else "good"),
            metric("Need human confirmation", sum(1 for r in rows if r["action"] == "human_triage_required"), "warn"),
            metric("Classifier macro-F1 (CV)", m["f1_macro"] if m else "n/a", hint=f"{m['cv_folds']}-fold CV on {len(pc.input['training'])} examples" if m else None),
            metric("Top priority", rows[0]["id"], tone_for_band(rows[0]["band"])),
        ],
        "charts": [chart("bar", "Calls by predicted category", [{"category": k, "calls": v} for k, v in sorted(counts.items())],
                         "category", [("calls", "Calls")])],
        "tables": [table("Dispatch queue (highest priority first)", [("id", "Id"), ("time", "Time"), ("category", "Category (p)"),
                         ("priority", "Priority"), ("action", "Action"), ("callback", "Callback"), ("call", "Caller said")], rows)],
        "narrative": narrative_of(pc, "overview", "summary"),
        "notes": ["Life-threat keywords override the model: rules are deterministic and always win.",
                  "The training set is small and synthetic; low-confidence predictions are routed to a human call-taker."],
    }


ADAPTER = DomainAdapter(
    id="public_safety", name="Public Safety & Emergency", icon="Siren", color="#ea580c",
    tagline="Classify emergency calls, catch life threats deterministically and order the dispatch queue",
    description="Trains a text classifier on labelled call transcripts (with cross-validated metrics), classifies incoming calls, extracts callback numbers, applies deterministic life-threat rules that override the model, computes a priority score and summarises the situation.",
    scenario="Emergency call triage", impact="Life-threatening calls rise to the top in seconds, with reasons a dispatcher can check.",
    input_model=Input, sample_file="public_safety.json", present=present,
    sections=["overview", "workspace", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("classify", "Classify calls", "ml", "text_classify",
             build=lambda pc: {"texts": [e["text"] for e in pc.input["training"]], "labels": [e["category"] for e in pc.input["training"]],
                               "predict": [i["caller_text"] for i in pc.input["incidents"]]}, why="TF-IDF + logistic regression, CV metrics"),
        Step("entities", "Extract callback details", "data", "extract_entities", foreach=True, optional=True,
             build=lambda pc: [{"text": i["caller_text"], "types": ["phone", "time"]} for i in pc.input["incidents"]]),
        Step("rules", "Life-threat rules", "decision", "evaluate_rules", build=_facts, why="Deterministic overrides"),
        Step("priority", "Priority scoring", "decision", "risk_score", build=_priority),
        Step("overview", "Situation summary", "ai", "summarize", optional=True,
             build=lambda pc: {"text": " ".join(f"{i['caller_text']}." for i in pc.input["incidents"]), "max_sentences": 3}),
    ],
)
