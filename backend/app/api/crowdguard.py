"""CROWDGUARD HTTP routes. Thin: every computation goes through the `crowd` engine via the registry,
so policy, validation, audit and the response envelope apply exactly as for any other operation."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from app.core.contracts import ExecutionContext
from app.crowdguard.media_analysis import make_sample_clip, sniff_media
from app.engines.crowd.engine import MEDIA_PROGRESS
from app.services import Services

from .deps import context, require, services
from .routes import _safe_name

router = APIRouter(prefix="/api/crowdguard", tags=["crowdguard"])
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
MAX_JOBS = 30


def _envelope(svc: Services, ctx: ExecutionContext, op: str, payload: dict[str, Any]) -> JSONResponse:
    resp = svc.registry.execute("crowd", op, payload, ctx)
    return JSONResponse(status_code=resp._status, content=resp.model_dump(mode="json"))


@router.get("/venue")
def venue(svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "venue", {})


@router.get("/status")
def status(svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "status", {})


@router.post("/simulation")
def simulation(payload: dict[str, Any] = Body(default_factory=dict), svc: Services = Depends(services),
               ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "simulate", payload)


@router.post("/assess")
def assess(payload: dict[str, Any] = Body(...), svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "assess", payload)


@router.post("/route")
def route(payload: dict[str, Any] = Body(...), svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "route", payload)


@router.post("/forecast")
def forecast(payload: dict[str, Any] = Body(...), svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "forecast", payload)


@router.post("/explain")
def explain(payload: dict[str, Any] = Body(default_factory=dict), svc: Services = Depends(services),
            ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "explain", payload)


# ------------------------------------------------------------------ Virtual Crowd Intelligence Engine (VCIE)
@router.get("/presets")
def vision_presets(svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "vision_presets", {})


@router.post("/calibration")
def vision_calibration(payload: dict[str, Any] = Body(...), svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "vision_calibrate", payload)


@router.post("/simulation/step")
def vision_step(scenario: str = "plaza_normal", mode: str = "gaussian", sigma: float = 28.0, steps: int = 1, views: bool = True,
                svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "vision_step", {"scenario": scenario, "mode": mode, "sigma": sigma, "steps": steps, "include_views": views})


@router.post("/simulation/reset")
def vision_reset(scenario: str = "plaza_normal", svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "vision_step", {"scenario": scenario, "reset": True})


VIEW_ATTR = {"frame": "latest_camera_frame", "birdseye": "latest_birdseye_frame", "heatmap": "latest_heatmap_frame",
             "movement": "latest_movement_frame", "digitaltwin": "latest_digital_twin_frame"}


@router.get("/analysis/live/tracks")
def vision_live_tracks(svc: Services = Depends(services)):
    p = svc.registry.get("crowd").vision_pipeline()
    with p.lock:
        res = p.latest_result
        if res is None:
            raise HTTPException(404, "No frame processed yet")
        return {"label": "SYNTHETIC", "frame_idx": res.frame_idx, "timestamp_s": res.timestamp_s,
                "active_tracks_count": res.active_tracks_count,
                "tracks": [t.model_dump(mode="json", exclude={"history"}) for t in res.tracks],
                "movement_vectors": [v.model_dump(mode="json") for v in res.movement_vectors],
                "zone_metrics": [z.model_dump(mode="json") for z in res.zone_metrics],
                "peak_density_per_sq_meter": res.peak_density_per_sq_meter,
                "alerts": [a.model_dump(mode="json") for a in res.alerts]}


@router.get("/analysis/live/{view}")
def vision_live_view(view: str, svc: Services = Depends(services)):
    """Latest frame of the live synthetic VCIE view as JPEG (the step response also embeds all five views)."""
    import cv2  # noqa: PLC0415

    attr = VIEW_ATTR.get(view)
    if attr is None:
        raise HTTPException(404, f"Unknown view '{view}'. Views: {sorted(VIEW_ATTR)}")
    p = svc.registry.get("crowd").vision_pipeline()
    with p.lock:
        img = getattr(p, attr)
        if img is None:
            raise HTTPException(404, "No frame rendered yet")
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise HTTPException(500, "Failed to encode frame")
    return Response(content=buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ incidents
@router.get("/incidents")
def incidents(status: str | None = None, svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "incident_list", {"status": status} if status else {})


@router.post("/incidents")
def open_incident(payload: dict[str, Any] = Body(...), svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "incident_open", payload)


@router.post("/incidents/{incident_id}/actions")
def incident_action(incident_id: str, payload: dict[str, Any] = Body(...), svc: Services = Depends(services),
                    ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "incident_update", {**payload, "incident_id": incident_id})


@router.get("/incidents/{incident_id}/verify")
def verify_incident(incident_id: str, svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    return _envelope(svc, ctx, "incident_verify", {"incident_id": incident_id})


# ------------------------------------------------------------------ media ingestion (background jobs)
def _store_media(svc: Services, ctx: ExecutionContext, filename: str, data: bytes, kind: str) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    ext = Path(filename).suffix.lower()[:8] or (".mp4" if kind == "video" else ".jpg")
    path = svc.settings.data_dir / "uploads" / f"{digest}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    mime = {"video": "video/mp4", "image": "image/jpeg"}[kind]
    doc = svc.store.add_document(filename=filename, content_type=mime, kind=kind, size=len(data), sha256=digest,
                                 storage_path=str(path), uploaded_by=ctx.actor)
    svc.store.audit("data", "media_uploaded", actor=ctx.actor, role=ctx.role,
                    detail={"document_id": doc["id"], "filename": filename, "sha256": digest, "size": len(data), "kind": kind})
    return doc


def _start_job(svc: Services, ctx: ExecutionContext, doc: dict[str, Any], options: dict[str, Any], provenance: dict | None = None) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "queued", "document_id": doc["id"], "filename": doc["filename"], "kind": doc["kind"],
           "created": time.time(), "provenance": provenance, "response": None}
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > MAX_JOBS:
            for old in sorted(_JOBS.values(), key=lambda j: j["created"])[: len(_JOBS) - MAX_JOBS]:
                _JOBS.pop(old["id"], None)
                MEDIA_PROGRESS.pop(old["id"], None)

    def work() -> None:
        job["status"] = "running"
        payload = {**options, "document_id": doc["id"], "job_id": job_id}
        resp = svc.registry.execute("crowd", "analyse_media", payload, ctx)
        job["response"] = resp.model_dump(mode="json")
        job["http_status"] = resp._status
        job["status"] = "completed" if resp.success else "failed"

    threading.Thread(target=work, name=f"crowd-media-{job_id}", daemon=True).start()
    return {"job_id": job_id, "status": "queued", "document": {k: doc[k] for k in ("id", "filename", "sha256", "size", "kind")},
            "provenance": provenance}


def _options(layout: str | None, custom_layout: str | None, venue_zone: str | None, coverage: float | None,
             max_seconds: float | None, target_fps: float | None) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if layout:
        opts["layout"] = layout
    if custom_layout:
        try:
            opts["custom_layout"] = json.loads(custom_layout)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"custom_layout is not valid JSON: {exc.msg}") from exc
    if venue_zone:
        opts["venue_zone"] = venue_zone
    if coverage:
        opts["coverage"] = coverage
    if max_seconds:
        opts["max_seconds"] = max_seconds
    if target_fps:
        opts["target_fps"] = target_fps
    return opts


@router.post("/media")
async def upload_media(file: UploadFile = File(...), layout: str | None = Form(None), custom_layout: str | None = Form(None),
                       venue_zone: str | None = Form(None), coverage: float | None = Form(None),
                       max_seconds: float | None = Form(None), target_fps: float | None = Form(None),
                       svc: Services = Depends(services), ctx: ExecutionContext = Depends(context)):
    require(svc, ctx, "data:write")
    limit = svc.settings.crowd_max_video_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {svc.settings.crowd_max_video_mb} MB")
    if not data:
        raise HTTPException(400, "Empty file")
    kind = sniff_media(data[:16])
    if kind is None:
        raise HTTPException(415, "Unsupported media. Allowed: JPEG, PNG, WEBP images; MP4/MOV, WebM/MKV, AVI video")
    filename = _safe_name(file.filename or "upload")
    doc = _store_media(svc, ctx, filename, data, kind)
    return _start_job(svc, ctx, doc, _options(layout, custom_layout, venue_zone, coverage, max_seconds, target_fps))


@router.post("/media/sample")
def sample_media(payload: dict[str, Any] = Body(default_factory=dict), svc: Services = Depends(services),
                 ctx: ExecutionContext = Depends(context)):
    require(svc, ctx, "data:write")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "crowdguard_test_clip.mp4"
        try:
            provenance = make_sample_clip(out)
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(503, f"Sample clip unavailable: {exc}") from exc
        data = out.read_bytes()
    doc = _store_media(svc, ctx, "crowdguard_test_clip.mp4", data, "video")
    opts = _options(payload.get("layout"), json.dumps(payload["custom_layout"]) if payload.get("custom_layout") else None,
                    payload.get("venue_zone"), payload.get("coverage"), payload.get("max_seconds"), payload.get("target_fps"))
    return _start_job(svc, ctx, doc, opts, provenance)


@router.get("/media/jobs")
def media_jobs():
    """Recent media jobs of this server process (newest first), without their results."""
    jobs = sorted(_JOBS.values(), key=lambda j: j["created"], reverse=True)
    return [{k: v for k, v in j.items() if k not in ("response",)} | {"progress": MEDIA_PROGRESS.get(j["id"], {})} for j in jobs]


@router.get("/media/jobs/{job_id}")
def media_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job (jobs are kept in memory and lost on restart)")
    out = {k: v for k, v in job.items() if k != "response"}
    out["progress"] = MEDIA_PROGRESS.get(job_id, {})
    if job["status"] in ("completed", "failed"):
        out["response"] = job["response"]
    return out
