import pytest
from sqlalchemy import update

from app.db.models import AuditEvent
from app.domains.registry import all_domains

DOMAINS = [d.id for d in all_domains()]


def test_health_and_engines(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"] == "ok"
    assert set(h["engines"]) == {"security", "ai", "ml", "crypto", "data", "decision"}
    engines = client.get("/api/engines").json()
    assert all(op["input_schema"] for e in engines for op in e["operations"])


def test_engine_call_envelope(client):
    r = client.post("/api/engines/crypto/hash", json={"text": "abc"})
    body = r.json()
    assert r.status_code == 200
    assert set(body) >= {"success", "engine", "result", "confidence", "execution_time_ms", "warnings", "metadata"}
    assert body["success"] and body["engine"] == "crypto" and body["confidence"] is None


@pytest.mark.parametrize("path,status,code", [
    ("/api/engines/nope/x", 404, "UNKNOWN_ENGINE"),
    ("/api/engines/crypto/nope", 404, "UNKNOWN_OPERATION"),
    ("/api/engines/crypto/hash", 422, "INVALID_INPUT"),
])
def test_engine_errors(client, path, status, code):
    r = client.post(path, json={})
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_role_headers(client):
    assert client.get("/api/whoami", headers={"X-Omniforge-Role": "reviewer"}).json()["role"] == "reviewer"
    assert client.get("/api/whoami", headers={"X-Omniforge-Role": "root"}).status_code == 400
    assert client.get("/api/whoami", headers={"X-Omniforge-Actor-Type": "system"}).status_code == 400
    r = client.post("/api/engines/crypto/generate_key", json={"label": "x"}, headers={"X-Omniforge-Role": "viewer"})
    assert r.status_code == 403


def test_upload_and_ingest(client):
    csv = b"a,b\n1,2\n3,4\n"
    doc = client.post("/api/documents", files={"file": ("../../evil name.csv", csv, "text/csv")}).json()
    assert doc["kind"] == "csv" and doc["filename"] == "evil name.csv" and "storage_path" not in doc
    ing = client.post("/api/engines/data/ingest", json={"name": "d", "document_id": doc["id"]}).json()
    assert ing["success"] and ing["result"]["row_count"] == 2
    ver = client.post("/api/engines/crypto/verify_document", json={"document_id": doc["id"]}).json()
    assert ver["result"]["intact"] is True


def test_upload_rejects_disguised_or_invalid_files(client):
    assert client.post("/api/documents", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}).status_code == 415
    assert client.post("/api/documents", files={"file": ("x.json", b"{not json", "application/json")}).status_code == 415
    assert client.post("/api/documents", files={"file": ("x.csv", b"", "text/csv")}).status_code == 400
    viewer = client.post("/api/documents", files={"file": ("a.csv", b"a\n1", "text/csv")}, headers={"X-Omniforge-Role": "viewer"})
    assert viewer.status_code == 403


def test_tampered_document_is_detected(client):
    doc = client.post("/api/documents", files={"file": ("e.txt", b"original evidence", "text/plain")}).json()
    svc = client.app.state.services
    path = svc.store.get_document(doc["id"])["storage_path"]
    with open(path, "ab") as fh:
        fh.write(b" altered")
    ver = client.post("/api/engines/crypto/verify_document", json={"document_id": doc["id"]}).json()
    assert ver["result"]["intact"] is False


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_domain_pipeline_runs_on_sample_data(client, domain):
    run = client.post(f"/api/domains/{domain}/run", json={}).json()
    assert run["status"] == "completed", run["error"]
    p = run["presentation"]
    assert p["headline"] and p["metrics"]
    assert all(s["status"] in ("completed", "skipped") for s in run["steps"])
    stored = client.get(f"/api/runs/{run['id']}").json()
    assert stored["status"] == "completed"


def test_pipeline_input_validation(client):
    run = client.post("/api/domains/cybersecurity/run", json={"input": {"messages": []}}).json()
    assert run["status"] == "failed" and "validation" in run["error"]


def test_viewer_cannot_run_pipelines(client):
    r = client.post("/api/domains/forensics/run", json={}, headers={"X-Omniforge-Role": "viewer"})
    assert r.status_code == 403


def test_finance_holds_require_human_approval(client):
    client.post("/api/domains/finance/run", json={}, headers={"X-Omniforge-Actor": "analyst-1"})
    pending = client.get("/api/approvals", params={"status": "pending"}).json()
    assert pending
    aid = pending[0]["id"]
    self_try = client.post(f"/api/approvals/{aid}/decision", json={"decision": "approve"},
                           headers={"X-Omniforge-Role": "reviewer", "X-Omniforge-Actor": "analyst-1"})
    assert self_try.status_code == 403
    ok = client.post(f"/api/approvals/{aid}/decision", json={"decision": "approve", "note": "confirmed with cardholder"},
                     headers={"X-Omniforge-Role": "reviewer", "X-Omniforge-Actor": "reviewer-1"})
    assert ok.status_code == 200 and ok.json()["result"]["status"] == "approved"


def test_audit_chain_detects_tampering(client):
    client.post("/api/domains/forensics/run", json={})
    assert client.get("/api/audit/verify").json()["valid"] is True
    svc = client.app.state.services
    with svc.store.session() as s:
        s.execute(update(AuditEvent).where(AuditEvent.id == 2).values(action="edited"))
    result = client.get("/api/audit/verify").json()
    assert result["valid"] is False and result["broken_at_id"] == 2


def test_settings_and_overview(client):
    s = client.put("/api/settings", json={"active_domain": "healthcare"}).json()
    assert s["active_domain"] == "healthcare" and "approvals" in s["sections"]
    assert client.put("/api/settings", json={"active_domain": "nope"}).status_code == 400
    ov = client.get("/api/overview").json()
    assert ov["active_domain"] == "healthcare" and ov["audit_chain"]["valid"]
    an = client.get("/api/analytics").json()
    assert "per_engine" in an and an["counts"]["audit_events"] > 0


def test_no_secrets_in_public_config(client):
    cfg = client.get("/api/config").json()
    assert not any("key" in k and isinstance(v, str) and len(v) > 20 for k, v in cfg.items())
