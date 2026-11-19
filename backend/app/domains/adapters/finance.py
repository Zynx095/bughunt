"""Finance & fraud prevention: real-time transaction screening with human holds."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table

FEATURES = ["amount", "hour", "merchant_category", "international", "card_present", "account_age_days",
            "txn_count_24h", "distance_from_home_km"]
NUMERIC = [f for f in FEATURES if f != "merchant_category"]


class Input(BaseModel):
    hold_threshold: float = Field(0.55, ge=0.05, le=0.95)
    history: list[dict[str, Any]] = Field(..., min_length=50, max_length=100_000, description="Labelled transactions (is_fraud 0/1)")
    incoming: list[dict[str, Any]] = Field(..., min_length=1, max_length=5_000)


def c(field, op, value):
    return {"field": field, "op": op, "value": value}


RULES = [
    {"id": "cnp-large", "description": "Card-not-present and amount > 1,500", "severity": "high", "outcome": "hold", "weight": 2,
     "when": {"all": [c("card_present", "eq", 0), c("amount", "gt", 1500)]}},
    {"id": "new-intl", "description": "International on an account younger than 30 days", "severity": "high", "outcome": "hold", "weight": 2,
     "when": {"all": [c("international", "eq", 1), c("account_age_days", "lt", 30)]}},
    {"id": "velocity", "description": "8+ transactions in 24 hours", "severity": "medium", "outcome": "step_up_auth",
     "when": c("txn_count_24h", "gte", 8)},
    {"id": "night-high", "description": "Night-time (00-05h) and amount > 800", "severity": "medium", "outcome": "step_up_auth",
     "when": {"all": [c("hour", "between", [0, 5]), c("amount", "gt", 800)]}},
    {"id": "gift-cards", "description": "Gift-card merchant", "severity": "low", "outcome": "monitor", "when": c("merchant_category", "eq", "gift_cards")},
]


def _anomaly(pc: PipelineContext) -> dict:
    rows = [{k: r.get(k) for k in ["txn_id"] + NUMERIC} for r in pc.input["history"]] + \
           [{k: r.get(k) for k in ["txn_id"] + NUMERIC} for r in pc.r("clean")["records"]]
    return {"records": rows, "id_field": "txn_id", "features": NUMERIC, "contamination": 0.08}


def _aggregate(pc: PipelineContext) -> dict:
    txns = pc.r("clean")["records"]
    preds = pc.r("model")["predictions"]
    anomalies = pc.r("anomaly")["rows"][-len(txns):]
    rules = pc.r("rules")["results"]
    items = []
    for t, p, a, r in zip(txns, preds, anomalies, rules):
        items.append({"id": t["txn_id"], "signals": [
            {"source": "fraud model", "score": p["probabilities"].get("1", 0.0), "weight": 0.5, "confidence": p["probability"]},
            {"source": "anomaly", "score": a["anomaly_score"], "weight": 0.2},
            {"source": "rules", "score": min(1.0, r["rule_score"] / 50), "weight": 0.3},
        ]})
    return {"items": items, "method": "weighted_mean", "decision_threshold": pc.input["hold_threshold"], "expected_sources": 3}


def _approvals(pc: PipelineContext) -> list[dict]:
    txns = {t["txn_id"]: t for t in pc.r("clean")["records"]}
    out = []
    for item in pc.r("aggregate")["items"]:
        if item["decision"] == "flag":
            t = txns[item["id"]]
            out.append({"title": f"Hold transaction {item['id']} ({t['amount']:.2f})", "action": "hold_transaction",
                        "risk_score": round(item["combined_score"] * 100, 1), "run_id": pc.run_id,
                        "payload": {"transaction": t, "signals": item["signals"], "confidence": item["confidence"]}})
    return out


def _explain(pc: PipelineContext):
    items = pc.r("aggregate")["items"]
    top = max(items, key=lambda i: i["combined_score"])
    if top["decision"] != "flag":
        return None
    idx = [i["id"] for i in items].index(top["id"])
    return {"subject": f"Transaction {top['id']}", "audience": "analyst", "context": {
        "score": round(top["combined_score"] * 100, 1), "decision": "hold for review", "confidence": top["confidence"],
        "matched": pc.r("rules")["results"][idx]["matched"],
        "contributions": [{"factor": s["source"], "points": round(s["score"] * s["weight"] * 100, 1)} for s in top["signals"]]}}


def present(pc: PipelineContext) -> dict:
    txns, items = pc.r("clean")["records"], pc.r("aggregate")["items"]
    model, rules = pc.r("model"), pc.r("rules")["results"]
    m = model["metrics"]
    rows = []
    for t, it, r in zip(txns, items, rules):
        sig = {s["source"]: s["score"] for s in it["signals"]}
        rows.append({"txn_id": t["txn_id"], "amount": t["amount"], "merchant": t["merchant_category"],
                     "model_p": round(sig["fraud model"], 3), "anomaly": round(sig["anomaly"], 3),
                     "rules": ", ".join(x["id"] for x in r["matched"]) or "—", "combined": round(it["combined_score"], 3),
                     "confidence": it["confidence"], "decision": "HOLD" if it["decision"] == "flag" else "approve"})
    held = [r for r in rows if r["decision"] == "HOLD"]
    rows.sort(key=lambda r: -r["combined"])
    return {
        "headline": f"{len(held)} of {len(rows)} incoming transactions held for analyst review ({sum(r['amount'] or 0 for r in held):,.2f} total)",
        "metrics": [
            metric("Held for review", len(held), "warn" if held else "good"),
            metric("Model F1 (holdout)", m["f1_macro"], hint=f"macro; majority baseline accuracy {m['baseline_majority_accuracy']}"),
            metric("Model ROC AUC", m.get("roc_auc", "n/a"), hint="holdout on synthetic history"),
            metric("Model recall (macro)", m["recall_macro"]),
            metric("Missing values imputed", pc.r("clean")["report"]["missing_values_before"]),
        ],
        "charts": [chart("bar", "Combined fraud score by transaction", [{"id": r["txn_id"], "score": r["combined"],
                         "band": "high" if r["decision"] == "HOLD" else "low"} for r in rows], "id", [("score", "Combined score")],
                         color_by="band", reference_lines=[{"y": pc.input["hold_threshold"], "label": "hold threshold"}], y_max=1),
                   chart("bar", "Top model features", model["feature_importance"][:8], "feature", [("importance", "Importance")], layout="vertical")],
        "tables": [table("Screening decisions", [("txn_id", "Txn"), ("amount", "Amount"), ("merchant", "Merchant"), ("model_p", "Model P(fraud)"),
                         ("anomaly", "Anomaly"), ("rules", "Rules"), ("combined", "Combined"), ("confidence", "Confidence"), ("decision", "Decision")], rows)],
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["All transactions and labels are synthetic (scripts/generate_sample_data.py); metrics show the pipeline works, not real-world accuracy.",
                  "Held transactions are queued in Approvals; a reviewer (not the model) makes the final call.",
                  "Confidence = signal agreement x coverage x model probability (heuristic, uncalibrated)."],
    }


ADAPTER = DomainAdapter(
    id="finance", name="Finance & Fraud Prevention", icon="Landmark", color="#4f46e5",
    tagline="Screen transactions with a supervised model, anomaly detection and rules — humans make the call",
    description="Cleans incoming transactions, trains and evaluates a fraud classifier on labelled history, scores anomalies, applies deterministic fraud rules, aggregates the three signals with a confidence estimate, and queues holds for human approval.",
    scenario="Card transaction fraud screening", impact="Fewer losses with fewer false declines: every hold is explained and reviewed.",
    input_model=Input, sample_file="finance.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "approvals", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("clean", "Clean incoming batch", "data", "clean", build=lambda pc: {"records": pc.input["incoming"], "fill_missing": "median"},
             why="Deduplicate and impute missing values"),
        Step("model", "Fraud classifier", "ml", "classify",
             build=lambda pc: {"records": pc.input["history"], "target": "is_fraud", "features": FEATURES, "model": "random_forest",
                               "predict": pc.r("clean")["records"]}, why="Random forest, stratified holdout metrics vs baseline"),
        Step("anomaly", "Anomaly detection", "ml", "anomaly", build=_anomaly, why="Unusual transactions relative to history"),
        Step("rules", "Fraud rules", "decision", "evaluate_rules",
             build=lambda pc: {"rules": RULES, "facts": pc.r("clean")["records"], "default_outcome": "approve"}, why="Known fraud patterns"),
        Step("aggregate", "Signal aggregation", "decision", "aggregate", build=_aggregate, why="Model + anomaly + rules, with confidence"),
        Step("approvals", "Queue holds", "decision", "request_approval", foreach=True, build=_approvals,
             why="Human approval required before any hold is final"),
        Step("explain", "Analyst explanation", "ai", "explain", optional=True, build=_explain),
    ],
)
