"""Cybersecurity & online safety: inbound message triage."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table, tone_for_band


class Message(BaseModel):
    id: str = Field(..., max_length=64)
    sender: str = Field(..., max_length=320)
    subject: str = Field("", max_length=500)
    body: str = Field(..., max_length=100_000)


class Input(BaseModel):
    messages: list[Message] = Field(..., min_length=1, max_length=200)


RULES = [
    {"id": "secret-leak", "description": "Credential or key material exposed", "severity": "critical", "outcome": "redact_and_alert",
     "when": {"field": "categories", "op": "contains", "value": "secret_exposure"}},
    {"id": "high-risk", "description": "Combined risk score is high", "severity": "high", "outcome": "quarantine",
     "when": {"field": "score", "op": "gte", "value": 55}},
    {"id": "ai-injection", "description": "Contains instructions aimed at AI assistants", "severity": "high", "outcome": "quarantine",
     "when": {"field": "injection_verdict", "op": "in", "value": ["review", "block"]}},
    {"id": "elevated", "description": "Moderate risk: warn the recipient", "severity": "medium", "outcome": "warn_recipient",
     "when": {"field": "score", "op": "between", "value": [25, 55]}},
]


def _text(m: dict) -> str:
    return f"From: {m['sender']}\nSubject: {m['subject']}\n\n{m['body']}"


def _risk_items(pc: PipelineContext) -> dict:
    items = []
    for m, scan, inj in zip(pc.input["messages"], pc.r("scan"), pc.r("injection")):
        url_findings = sum(1 for f in scan["findings"] if f["category"] == "suspicious_url")
        items.append({"id": m["id"], "factors": [
            {"name": "threat indicators", "value": scan["risk_score"], "max": 100, "weight": 3},
            {"name": "prompt-injection signals", "value": inj["injection_score"], "max": 100, "weight": 2},
            {"name": "suspicious URL findings", "value": url_findings, "max": 4, "weight": 1},
        ]})
    return {"items": items}


def _facts(pc: PipelineContext) -> dict:
    facts = []
    for scan, inj, risk in zip(pc.r("scan"), pc.r("injection"), pc.r("score")["items"]):
        facts.append({"score": risk["score"], "categories": scan["categories"], "injection_verdict": inj["verdict"]})
    return {"rules": RULES, "facts": facts, "default_outcome": "deliver"}


def _explain(pc: PipelineContext) -> dict | None:
    risks = pc.r("score")["items"]
    i = max(range(len(risks)), key=lambda k: risks[k]["score"])
    if risks[i]["score"] < 25:
        return None
    m, scan, rule = pc.input["messages"][i], pc.r("scan")[i], pc.r("policy")["results"][i]
    return {"subject": f"Message {m['id']} from {m['sender']}", "audience": "analyst", "context": {
        "score": risks[i]["score"], "band": risks[i]["band"], "outcome": rule["outcome"],
        "contributions": risks[i]["contributions"], "findings": scan["findings"][:6]}}


def present(pc: PipelineContext) -> dict:
    msgs, scans, injs = pc.input["messages"], pc.r("scan"), pc.r("injection")
    risks, rules = pc.r("score")["items"], pc.r("policy")["results"]
    rows = []
    for m, s, inj, r, rule in zip(msgs, scans, injs, risks, rules):
        top = max(s["findings"], key=lambda f: {"critical": 4, "high": 3, "medium": 2, "low": 1}[f["severity"]], default=None)
        rows.append({"id": m["id"], "sender": m["sender"], "subject": m["subject"], "score": r["score"], "band": r["band"],
                     "action": rule["outcome"], "injection": inj["verdict"],
                     "top_finding": top["description"] if top else "—", "findings": len(s["findings"])})
    rows.sort(key=lambda x: -x["score"])
    actions = [r["action"] for r in rows]
    need = sum(1 for a in actions if a != "deliver")
    return {
        "headline": f"{need} of {len(rows)} messages need action before delivery",
        "metrics": [
            metric("Quarantined", actions.count("quarantine"), "bad" if "quarantine" in actions else "good"),
            metric("Secrets redacted", actions.count("redact_and_alert"), "bad" if "redact_and_alert" in actions else "good"),
            metric("Warned", actions.count("warn_recipient"), "warn"),
            metric("Delivered", actions.count("deliver"), "good"),
            metric("AI-injection attempts", sum(1 for r in rows if r["injection"] != "allow"), "warn"),
        ],
        "charts": [chart("bar", "Risk score by message", [{"id": r["id"], "score": r["score"], "band": r["band"]} for r in rows],
                         "id", [("score", "Risk score")], color_by="band", y_max=100)],
        "tables": [table("Triage decisions", [("id", "Message"), ("sender", "Sender"), ("subject", "Subject"), ("score", "Risk"),
                                             ("band", "Band"), ("action", "Action"), ("top_finding", "Top finding")], rows)],
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["Scores come from deterministic, auditable rules; each finding names the rule that fired.",
                  "Prompt-injection screening protects any AI assistant that later reads these messages."],
    }


ADAPTER = DomainAdapter(
    id="cybersecurity", name="Cybersecurity & Online Safety", icon="ShieldAlert", color="#e11d48",
    tagline="Triage inbound messages for phishing, injection payloads, leaked secrets and AI-targeted attacks",
    description="Scans each message with deterministic threat rules and URL heuristics, screens for prompt injection aimed at AI assistants, combines the signals into an explainable risk score, and applies a policy that decides deliver / warn / quarantine / redact.",
    scenario="Inbound message triage", impact="Cuts analyst triage time by ranking messages and explaining every decision.",
    input_model=Input, sample_file="cybersecurity.json", present=present,
    sections=["overview", "workspace", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("scan", "Threat scan", "security", "threat_scan", foreach=True,
             build=lambda pc: [{"text": _text(m), "source": m["id"]} for m in pc.input["messages"]],
             why="Pattern rules for injection payloads, secrets, social engineering and URL red flags"),
        Step("injection", "Prompt-injection screen", "security", "prompt_injection", foreach=True,
             build=lambda pc: [{"text": m["body"], "source": m["id"]} for m in pc.input["messages"]],
             why="Messages are often summarised by AI assistants; hidden instructions must be caught first"),
        Step("score", "Risk scoring", "decision", "risk_score", build=_risk_items, why="Weighted, explainable 0-100 score"),
        Step("policy", "Delivery policy", "decision", "evaluate_rules", build=_facts, why="Deterministic action per message"),
        Step("explain", "Analyst explanation", "ai", "explain", build=_explain, optional=True,
             why="Plain-language rationale for the highest-risk message"),
    ],
)
