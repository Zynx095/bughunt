"""Healthcare & well-being: privacy-preserving remote vitals early warning."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, narrative_of, table, tone_for_band

PSEUDONYM_KEY, PHI_KEY = "patient-pseudonym", "phi-encryption"


class Reading(BaseModel):
    timestamp: str
    heart_rate: float = Field(..., ge=0, le=300)
    spo2: float = Field(..., ge=0, le=100)
    systolic_bp: float = Field(..., ge=0, le=300)
    resp_rate: float = Field(..., ge=0, le=80)
    temperature_c: float = Field(..., ge=25, le=45)


class Input(BaseModel):
    patient_ref: str = Field(..., max_length=128, description="Direct identifier: pseudonymised and encrypted, never displayed")
    ward: str = ""
    readings: list[Reading] = Field(..., min_length=8, max_length=20_000)


def c(field, op, value):
    return {"field": field, "op": op, "value": value}


# Thresholds inspired by the UK NEWS2 bands. Illustrative only: NOT clinically validated.
RULES = [
    {"id": "spo2-low", "description": "SpO2 <= 91%", "severity": "high", "outcome": "urgent_review", "when": c("spo2", "lte", 91)},
    {"id": "rr-extreme", "description": "Respiratory rate >= 25 or <= 8", "severity": "high", "outcome": "urgent_review",
     "when": {"any": [c("resp_rate", "gte", 25), c("resp_rate", "lte", 8)]}},
    {"id": "hr-extreme", "description": "Heart rate >= 131 or <= 40", "severity": "high", "outcome": "urgent_review",
     "when": {"any": [c("heart_rate", "gte", 131), c("heart_rate", "lte", 40)]}},
    {"id": "sbp-low", "description": "Systolic BP <= 90", "severity": "high", "outcome": "urgent_review", "when": c("systolic_bp", "lte", 90)},
    {"id": "spo2-borderline", "description": "SpO2 92-93%", "severity": "medium", "outcome": "increase_monitoring", "when": c("spo2", "between", [92, 93.99])},
    {"id": "hr-high", "description": "Heart rate 111-130", "severity": "medium", "outcome": "increase_monitoring", "when": c("heart_rate", "between", [111, 130.99])},
    {"id": "rr-high", "description": "Respiratory rate 21-24", "severity": "medium", "outcome": "increase_monitoring", "when": c("resp_rate", "between", [21, 24.99])},
    {"id": "fever", "description": "Temperature >= 39.1 C", "severity": "medium", "outcome": "increase_monitoring", "when": c("temperature_c", "gte", 39.1)},
]
VITALS = ["heart_rate", "spo2", "systolic_bp", "resp_rate", "temperature_c"]


def _risk(pc: PipelineContext) -> dict:
    last = pc.input["readings"][-1]
    last_anom = pc.r("anomaly")["rows"][-1]["anomaly_score"]
    return {"factors": [
        {"name": "SpO2", "value": last["spo2"], "min": 86, "max": 97, "invert": True, "weight": 3},
        {"name": "respiratory rate", "value": last["resp_rate"], "min": 14, "max": 28, "weight": 3},
        {"name": "heart rate", "value": last["heart_rate"], "min": 70, "max": 135, "weight": 2},
        {"name": "systolic BP", "value": last["systolic_bp"], "min": 85, "max": 125, "invert": True, "weight": 2},
        {"name": "temperature", "value": last["temperature_c"], "min": 37.0, "max": 39.5, "weight": 1},
        {"name": "deviation from own baseline", "value": last_anom, "weight": 1},
    ]}


def _approval(pc: PipelineContext):
    risk = pc.r("risk")
    if risk["band"] not in ("high", "critical"):
        return None
    pseudo = pc.vars["pseudonym"]
    return {"title": f"Rapid-response review for patient {pseudo}", "action": "escalate_to_rapid_response",
            "risk_score": risk["score"], "run_id": pc.run_id,
            "payload": {"pseudonym": pseudo, "ward": pc.input["ward"], "band": risk["band"],
                        "latest": pc.input["readings"][-1], "top_factors": risk["contributions"][:3]}}


def _pseudonym(pc: PipelineContext) -> dict:
    return {"text": pc.input["patient_ref"], "key_label": PSEUDONYM_KEY}


def _encrypt(pc: PipelineContext) -> dict:
    pc.vars["pseudonym"] = "P-" + pc.r("pseudonym")["hmac_sha256"][:12]
    return {"text": pc.input["patient_ref"], "key_label": PHI_KEY, "associated_data": pc.vars["pseudonym"]}


def present(pc: PipelineContext) -> dict:
    readings, rules, risk = pc.input["readings"], pc.r("rules")["results"], pc.r("risk")
    alerts = [{"timestamp": r["timestamp"].replace("T", " "), "severity": res["max_severity"],
               "rules": ", ".join(m["description"] for m in res["matched"])}
              for r, res in zip(readings, rules) if res["matched"]]
    first_high = next((a["timestamp"] for a in alerts if a["severity"] == "high"), None)
    approval = pc.r("approval")
    data = [{"t": r["timestamp"][11:16], **{k: r[k] for k in VITALS}} for r in readings]
    enc = pc.r("encrypt")
    return {
        "headline": f"Patient {pc.vars['pseudonym']}: latest risk {risk['score']:.0f}/100 ({risk['band'].upper()})"
                    + ("; rapid-response review requested" if approval else ""),
        "metrics": [
            metric("Pseudonymous id", pc.vars["pseudonym"], hint="HMAC-SHA256 of the identifier under a managed key"),
            metric("Latest risk", f"{risk['score']:.0f}/100", tone_for_band(risk["band"]), hint=risk["band"]),
            metric("Readings with alerts", f"{len(alerts)}/{len(readings)}", "warn" if alerts else "good"),
            metric("First high-severity alert", first_high or "none", "bad" if first_high else "good"),
            metric("Clinician approval", approval["status"] if approval else "not required", "warn" if approval else "neutral"),
        ],
        "charts": [chart("line", "Vital signs", data, "t", [("heart_rate", "Heart rate"), ("resp_rate", "Resp. rate"),
                                                             ("spo2", "SpO2 %"), ("systolic_bp", "Systolic BP")])],
        "tables": [table("Risk contributions (latest reading)", [("factor", "Factor"), ("value", "Value"), ("points", "Points")], risk["contributions"]),
                   table("Threshold alerts", [("timestamp", "Time"), ("severity", "Severity"), ("rules", "Rules matched")], alerts[-15:])],
        "artifacts": {"encrypted_identifier": {k: enc[k] for k in ("algorithm", "key_label", "nonce_b64", "ciphertext_b64", "associated_data")}},
        "narrative": narrative_of(pc, "explain", "explanation"),
        "notes": ["Thresholds are NEWS2-inspired for demonstration and are NOT clinically validated.",
                  "The identifier is stored only as an HMAC pseudonym and AES-256-GCM ciphertext; decryption needs the reviewer role.",
                  "Escalation is queued for a human clinician; the system never escalates or treats autonomously."],
    }


ADAPTER = DomainAdapter(
    id="healthcare", name="Healthcare & Well-being", icon="HeartPulse", color="#059669",
    tagline="Early-warning on remote vitals with pseudonymised identifiers and clinician sign-off",
    description="Pseudonymises and encrypts the patient identifier, checks every reading against NEWS2-inspired thresholds, detects deviation from the patient's own baseline, scores current risk with an explainable breakdown, and queues high-risk cases for clinician approval.",
    scenario="Remote patient deterioration early warning", impact="Surfaces deterioration hours earlier while keeping identifiers out of analytics.",
    input_model=Input, sample_file="healthcare.json", present=present,
    sections=["overview", "workspace", "runs", "approvals", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("pseudo_key", "Pseudonym key", "crypto", "generate_key", build=lambda pc: {"label": PSEUDONYM_KEY, "key_type": "hmac"},
             why="Keyed pseudonyms cannot be reversed by brute-forcing identifiers"),
        Step("pseudonym", "Pseudonymise identifier", "crypto", "hmac", build=_pseudonym, why="HMAC-SHA256"),
        Step("phi_key", "PHI encryption key", "crypto", "generate_key", build=lambda pc: {"label": PHI_KEY, "key_type": "aes256"}),
        Step("encrypt", "Encrypt identifier", "crypto", "encrypt", build=_encrypt, why="AES-256-GCM bound to the pseudonym as associated data"),
        Step("rules", "Threshold checks", "decision", "evaluate_rules",
             build=lambda pc: {"rules": RULES, "facts": pc.input["readings"], "default_outcome": "routine"}, why="NEWS2-inspired bands per reading"),
        Step("anomaly", "Personal baseline deviation", "ml", "anomaly",
             build=lambda pc: {"records": pc.input["readings"], "features": VITALS, "id_field": "timestamp", "contamination": 0.1},
             why="Catches unusual combinations even below fixed thresholds"),
        Step("risk", "Current risk score", "decision", "risk_score", build=_risk, why="Explainable weighted score for the latest reading"),
        Step("approval", "Clinician escalation", "decision", "request_approval", build=_approval,
             why="High risk is queued for a human; nothing is escalated automatically"),
        Step("explain", "Clinical summary", "ai", "explain", optional=True,
             build=lambda pc: {"subject": f"Patient {pc.vars['pseudonym']}", "audience": "analyst", "context": {
                 "score": pc.r("risk")["score"], "band": pc.r("risk")["band"], "contributions": pc.r("risk")["contributions"],
                 "matched": pc.r("rules")["results"][-1]["matched"],
                 "recommendation": "clinician review of the latest observations" if pc.r("approval") else "continue routine monitoring"}}),
    ],
)
