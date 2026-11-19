"""Digital forensics: evidence sealing and chain of custody."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, metric, table

SIGNING_KEY = "forensics-case-signing"


class Evidence(BaseModel):
    name: str = Field(..., max_length=255)
    content: str = Field(..., max_length=5_000_000)


class TamperCheck(BaseModel):
    index: int = Field(..., ge=0)
    altered_content: str


class Input(BaseModel):
    case_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    examiner: str = Field(..., max_length=128)
    evidence: list[Evidence] = Field(..., min_length=1, max_length=5000)
    tamper_check: TamperCheck | None = Field(None, description="Optional: demonstrate detection of an altered item")


def _manifest(pc: PipelineContext) -> dict:
    digests = [h["digest"] for h in pc.r("hashes")]
    manifest = {
        "case_id": pc.input["case_id"], "examiner": pc.input["examiner"], "sealed_run": pc.run_id,
        "merkle_root": pc.r("merkle")["root"], "hash_algorithm": "SHA-256",
        "items": [{"name": e["name"], "sha256": d} for e, d in zip(pc.input["evidence"], digests)],
    }
    pc.vars["manifest"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return {"text": pc.vars["manifest"], "key_label": SIGNING_KEY}


def _tamper_hashes(pc: PipelineContext):
    tc = pc.input.get("tamper_check")
    if not tc or tc["index"] >= len(pc.input["evidence"]):
        return None
    return {"text": tc["altered_content"]}


def _tamper_verify(pc: PipelineContext):
    tc, altered = pc.input.get("tamper_check"), pc.r("tamper_hash")
    if not tc or not altered:
        return None
    i, merkle = tc["index"], pc.r("merkle")
    proof = merkle["proofs"][i]
    original = pc.r("hashes")[i]["digest"]
    return [{"leaf": original, "leaf_encoding": "sha256_hex", "proof": proof, "root": merkle["root"]},
            {"leaf": altered["digest"], "leaf_encoding": "sha256_hex", "proof": proof, "root": merkle["root"]}]


def present(pc: PipelineContext) -> dict:
    merkle, sig, ver = pc.r("merkle"), pc.r("sign"), pc.r("verify_sig")
    rows = [{"#": i, "name": e["name"], "sha256": h["digest"], "bytes": h["bytes"], "proof_steps": len(merkle["proofs"][i])}
            for i, (e, h) in enumerate(zip(pc.input["evidence"], pc.r("hashes")))]
    tamper = pc.r("tamper_verify")
    metrics = [
        metric("Evidence items", len(rows)),
        metric("Merkle root", merkle["root"][:16] + "…", hint=merkle["root"]),
        metric("Manifest signature", "valid" if ver and ver["valid"] else "INVALID", "good" if ver and ver["valid"] else "bad"),
    ]
    notes = ["The Ed25519 signature covers the case id, examiner, run id, every item hash and the Merkle root.",
             "Any later change to an item changes its hash, so its inclusion proof no longer reaches the signed root."]
    if tamper:
        original_ok, altered_ok = tamper[0]["valid"], tamper[1]["valid"]
        metrics.append(metric("Tamper test", "detected" if original_ok and not altered_ok else "NOT detected",
                              "good" if original_ok and not altered_ok else "bad",
                              hint="original item verifies; altered copy fails" if original_ok and not altered_ok else None))
    iocs = pc.r("iocs") or {"entities": {}}
    ioc_rows = [{"type": t, "value": v} for t, vals in iocs["entities"].items() for v in vals]
    return {
        "headline": f"Case {pc.input['case_id']}: {len(rows)} items sealed under Merkle root {merkle['root'][:12]}…",
        "metrics": metrics,
        "charts": [],
        "tables": [table("Evidence manifest", [("#", "#"), ("name", "Item"), ("sha256", "SHA-256"), ("bytes", "Bytes"),
                                               ("proof_steps", "Proof length")], rows),
                   table("Indicators of compromise", [("type", "Type"), ("value", "Value")], ioc_rows)],
        "artifacts": {"manifest": pc.vars.get("manifest"), "signature_b64": sig["signature_b64"] if sig else None,
                      "public_key_pem": sig["public_key_pem"] if sig else None},
        "narrative": None,
        "notes": notes,
    }


ADAPTER = DomainAdapter(
    id="forensics", name="Digital Forensics", icon="Fingerprint", color="#7c3aed",
    tagline="Seal evidence with hashes, a Merkle root and a signed manifest; prove later tampering",
    description="Hashes every evidence item, builds an RFC 6962-style Merkle tree, signs a canonical case manifest with a managed Ed25519 key, verifies the signature, demonstrates tamper detection with inclusion proofs, and extracts indicators of compromise.",
    scenario="Evidence intake & chain of custody", impact="Makes evidence integrity independently verifiable by anyone holding the public key.",
    input_model=Input, sample_file="forensics.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "engines", "audit", "settings"],
    steps=[
        Step("hashes", "Hash evidence", "crypto", "hash", foreach=True,
             build=lambda pc: [{"text": e["content"]} for e in pc.input["evidence"]], why="SHA-256 fingerprint per item"),
        Step("merkle", "Merkle tree", "crypto", "merkle_root",
             build=lambda pc: {"leaves": [h["digest"] for h in pc.r("hashes")], "leaf_encoding": "sha256_hex", "include_proofs": True},
             why="One root commits to the whole evidence set; per-item inclusion proofs"),
        Step("key", "Case signing key", "crypto", "generate_key",
             build=lambda pc: {"label": SIGNING_KEY, "key_type": "ed25519"}, why="Managed Ed25519 key (secret never leaves the key store)"),
        Step("sign", "Sign manifest", "crypto", "sign", build=_manifest, why="Binds examiner, case and root (requires crypto:sign)"),
        Step("verify_sig", "Verify signature", "crypto", "verify",
             build=lambda pc: {"text": pc.vars["manifest"], "signature_b64": pc.r("sign")["signature_b64"],
                               "public_key_pem": pc.r("sign")["public_key_pem"]}, why="Independent verification with the public key"),
        Step("tamper_hash", "Hash altered copy", "crypto", "hash", build=_tamper_hashes, optional=True,
             why="Simulated modification of one item"),
        Step("tamper_verify", "Tamper detection", "crypto", "merkle_verify", foreach=True, build=_tamper_verify, optional=True,
             why="Original item verifies against the signed root; the altered copy must not"),
        Step("iocs", "Extract indicators", "data", "extract_entities",
             build=lambda pc: {"text": "\n".join(e["content"] for e in pc.input["evidence"]),
                               "types": ["ipv4", "email", "url", "sha256", "btc_address", "cve", "phone"]},
             why="IPs, addresses, hashes and CVEs for the investigation"),
    ],
)
