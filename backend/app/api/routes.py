"""HTTP API. Thin layer: validation, identity context, and delegation to the
registry / pipeline runner / store."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.contracts import ExecutionContext
from app.domains.base import ALL_SECTIONS, run_pipeline
from app.domains.registry import DEFAULT_DOMAIN, all_domains, get_domain
from app.services import Services

from .deps import context, require, services

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ system
@router.get("/health", tags=["system"])
def health(svc: Services = Depends(services)) -> dict[str, Any]:
    try:
        db_ok = svc.store.ping()
    except Exception:  # noqa: BLE001
        db_ok = False
    engines = svc.registry.health()
    degraded = (not db_ok) or any(h.get("status") != "ok" for h in engines.values())
    return {"status": "degraded" if degraded else "ok", "version": svc.settings.version,
            "database": "ok" if db_ok else "error", "engines": engines}


@router.get("/config", tags=["system"])
def public_config(svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.settings.public_view()


@router.get("/whoami", tags=["system"])
def whoami(ctx: ExecutionContext = Depends(context)) -> dict[str, Any]:
    return {"actor": ctx.actor, "role": ctx.role, "actor_type": ctx.actor_type, "authenticated": False,
            "note": "Identity is declared via headers in the foundation build (simulated)."}


# ------------------------------------------------------------------ engines
@router.get("/engines", tags=["engines"])
def list_engines(svc: Services = Depends(services)) -> list[dict[str, Any]]:
    return svc.registry.describe()


@router.get("/engines/{name}", tags=["engines"])
def get_engine(name: str, svc: Services = Depends(services)) -> dict[str, Any]:
    engine = svc.registry.get(name)
    if engine is None:
        raise HTTPException(404, f"No engine named '{name}'")
    return engine.describe()


@router.post("/engines/{name}/{operation}", tags=["engines"])
def execute(name: str, operation: str, payload: dict[str, Any] = Body(default_factory=dict),
            svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)) -> JSONResponse:
    resp = svc.registry.execute(name, operation, payload, ctx)
    return JSONResponse(status_code=resp._status, content=resp.model_dump(mode="json"))


# ------------------------------------------------------------------ domains & runs
class RunRequest(BaseModel):
    input: dict[str, Any] | None = Field(None, description="Scenario input; omit to use the bundled sample data")


@router.get("/domains", tags=["domains"])
def list_domains() -> list[dict[str, Any]]:
    return [d.describe() for d in all_domains()]


@router.get("/domains/{domain_id}", tags=["domains"])
def domain_detail(domain_id: str) -> dict[str, Any]:
    d = get_domain(domain_id)
    if d is None:
        raise HTTPException(404, f"Unknown domain '{domain_id}'")
    return d.describe(with_sample=True)


@router.post("/domains/{domain_id}/run", tags=["domains"])
def run_domain(domain_id: str, req: RunRequest = Body(default_factory=RunRequest),
               svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)) -> dict[str, Any]:
    d = get_domain(domain_id)
    if d is None:
        raise HTTPException(404, f"Unknown domain '{domain_id}'")
    require(svc, ctx, "pipeline:run")
    return run_pipeline(d, req.input, svc.registry, svc.store, ctx)


@router.get("/runs", tags=["domains"])
def list_runs(domain: str | None = None, limit: int = Query(50, ge=1, le=500), svc: Services = Depends(services)):
    return svc.store.list_runs(limit=limit, domain=domain)


@router.get("/runs/{run_id}", tags=["domains"])
def get_run(run_id: str, svc: Services = Depends(services)) -> dict[str, Any]:
    run = svc.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


# ------------------------------------------------------------------ settings
class SettingsUpdate(BaseModel):
    active_domain: str


@router.get("/settings", tags=["settings"])
def get_settings_view(svc: Services = Depends(services)) -> dict[str, Any]:
    active = svc.store.get_setting("active_domain", DEFAULT_DOMAIN)
    if get_domain(active) is None:
        active = DEFAULT_DOMAIN
    return {"active_domain": active, "sections": get_domain(active).sections, "all_sections": ALL_SECTIONS,
            "config": svc.settings.public_view()}


@router.put("/settings", tags=["settings"])
def update_settings(update: SettingsUpdate, svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    if get_domain(update.active_domain) is None:
        raise HTTPException(400, f"Unknown domain '{update.active_domain}'")
    require(svc, ctx, "settings:write")
    svc.store.set_setting("active_domain", update.active_domain)
    svc.store.audit("settings", "active_domain_changed", actor=ctx.actor, role=ctx.role, detail={"active_domain": update.active_domain})
    return get_settings_view(svc)


# ------------------------------------------------------------------ documents & datasets
MAGIC = [(b"%PDF-", "pdf", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "image", "image/png"),
         (b"\xff\xd8\xff", "image", "image/jpeg")]
TEXT_KINDS = {".csv": ("csv", "text/csv"), ".json": ("json", "application/json"), ".txt": ("txt", "text/plain"),
              ".md": ("txt", "text/markdown"), ".log": ("txt", "text/plain")}


def _sniff(filename: str, head: bytes, data: bytes) -> tuple[str, str]:
    for magic, kind, mime in MAGIC:
        if head.startswith(magic):
            return kind, mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    ext = Path(filename).suffix.lower()
    if ext in TEXT_KINDS:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "Text files must be UTF-8") from exc
        if "\x00" in text:
            raise HTTPException(415, "Binary content in a text file")
        if ext == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise HTTPException(415, f"Invalid JSON: {exc.msg}") from exc
        return TEXT_KINDS[ext]
    raise HTTPException(415, "Unsupported file type. Allowed: PDF, PNG, JPEG, WEBP, CSV, JSON, TXT/MD/LOG")


def _safe_name(name: str) -> str:
    base = Path(name or "upload").name
    cleaned = re.sub(r"[^A-Za-z0-9 _.\-]", "_", base).strip(" .") or "upload"
    return cleaned[:200]


@router.post("/documents", tags=["data"])
async def upload_document(file: UploadFile = File(...), svc: Services = Depends(services),
                          ctx: ExecutionContext = Depends(context)) -> dict[str, Any]:
    require(svc, ctx, "data:write")
    limit = svc.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {svc.settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Empty file")
    filename = _safe_name(file.filename or "upload")
    kind, mime = _sniff(filename, data[:16], data)
    digest = hashlib.sha256(data).hexdigest()
    path = svc.settings.data_dir / "uploads" / f"{digest}{Path(filename).suffix.lower()[:8]}"
    if not path.exists():
        path.write_bytes(data)
    doc = svc.store.add_document(filename=filename, content_type=mime, kind=kind, size=len(data), sha256=digest,
                                 storage_path=str(path), uploaded_by=ctx.actor)
    svc.store.audit("data", "document_uploaded", actor=ctx.actor, role=ctx.role,
                    detail={"document_id": doc["id"], "filename": filename, "sha256": digest, "size": len(data)})
    doc.pop("storage_path", None)
    return doc


@router.get("/documents", tags=["data"])
def list_documents(svc: Services = Depends(services)) -> list[dict[str, Any]]:
    docs = svc.store.list_documents()
    for d in docs:
        d.pop("storage_path", None)
    return docs


@router.get("/datasets", tags=["data"])
def list_datasets(svc: Services = Depends(services)) -> list[dict[str, Any]]:
    return svc.store.list_datasets()


@router.get("/datasets/{dataset_id}", tags=["data"])
def get_dataset(dataset_id: str, limit: int = Query(50, ge=1, le=1000), svc: Services = Depends(services)) -> dict[str, Any]:
    ds = svc.store.get_dataset(dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    ds["preview"] = ds.pop("records")[:limit]
    return ds


# ------------------------------------------------------------------ audit, approvals, analytics
@router.get("/audit", tags=["audit"])
def audit_log(limit: int = Query(100, ge=1, le=1000), category: str | None = None, svc: Services = Depends(services)):
    return svc.store.list_audit(limit=limit, category=category)


@router.get("/audit/verify", tags=["audit"])
def verify_audit(svc: Services = Depends(services)) -> dict[str, Any]:
    return svc.store.verify_audit_chain()


@router.get("/executions", tags=["audit"])
def executions(limit: int = Query(100, ge=1, le=1000), svc: Services = Depends(services)):
    return svc.store.list_executions(limit=limit)


@router.get("/approvals", tags=["approvals"])
def approvals(status: str | None = None, svc: Services = Depends(services)):
    return svc.store.list_approvals(status=status)


class DecisionRequest(BaseModel):
    decision: str
    note: str | None = None


@router.post("/approvals/{approval_id}/decision", tags=["approvals"])
def decide(approval_id: str, req: DecisionRequest, svc: Services = Depends(services),
           ctx: ExecutionContext = Depends(context)) -> JSONResponse:
    resp = svc.registry.execute("decision", "decide_approval",
                                {"approval_id": approval_id, "decision": req.decision, "note": req.note}, ctx)
    return JSONResponse(status_code=resp._status, content=resp.model_dump(mode="json"))


@router.get("/analytics", tags=["analytics"])
def analytics(svc: Services = Depends(services)) -> dict[str, Any]:
    recent = svc.store.list_executions(limit=300)
    return {"counts": svc.store.counts(), **svc.store.execution_stats(),
            "recent": [{"id": e["id"], "engine": e["engine"], "operation": e["operation"], "ms": e["execution_time_ms"],
                        "success": e["success"], "at": e["created_at"]} for e in reversed(recent)]}


@router.get("/overview", tags=["analytics"])
def overview(svc: Services = Depends(services)) -> dict[str, Any]:
    active = svc.store.get_setting("active_domain", DEFAULT_DOMAIN)
    return {"counts": svc.store.counts(), "health": health(svc), "active_domain": active,
            "recent_runs": svc.store.list_runs(limit=8), "recent_audit": svc.store.list_audit(limit=8),
            "audit_chain": svc.store.verify_audit_chain()}
