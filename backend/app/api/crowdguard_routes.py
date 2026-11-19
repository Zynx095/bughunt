"""FastAPI REST routes for CrowdGuard Virtual Crowd Intelligence Engine (VCIE)."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional
import cv2
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.crowdguard.calibration import CameraCalibrationEngine
from app.crowdguard.pipeline import VirtualCrowdIntelligencePipeline
from app.crowdguard.schemas import (
    AnalysisJobSummary,
    CalibrationConfig,
    CalibrationPoint,
    CalibrationQuad,
    CalibrationResult,
    FrameAnalysisResult,
    HeatmapMode,
    MovementVector,
    TrackedPerson,
    VideoProcessingConfig,
    ZoneMetric,
)
from app.crowdguard.venue import VenueDigitalTwin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crowdguard", tags=["crowdguard"])

# Global in-memory pipeline state and background job registry
_default_pipeline: Optional[VirtualCrowdIntelligencePipeline] = None
_active_jobs: Dict[str, AnalysisJobSummary] = {}
_job_pipelines: Dict[str, VirtualCrowdIntelligencePipeline] = {}
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "crowdguard_uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_default_pipeline() -> VirtualCrowdIntelligencePipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = VirtualCrowdIntelligencePipeline()
        # Initialize with 1 synthetic step so default frames exist
        _default_pipeline.step_synthetic(scenario="plaza_normal")
    return _default_pipeline


@router.get("/presets")
async def get_venue_and_calibration_presets():
    """Returns available venue models, calibration presets, and simulation scenarios."""
    pipeline = get_default_pipeline()
    calib_preset = pipeline.calibration.config
    venue_model = pipeline.venue.model
    scenarios = [
        {"id": "plaza_normal", "name": "Plaza Multi-Directional Flow", "description": "35 pedestrians traversing open concourse and gathering areas."},
        {"id": "bottleneck", "name": "Narrow Corridor Bottleneck", "description": "45 pedestrians funneling through constricted exit; highlights stagnation."},
        {"id": "counterflow", "name": "Bidirectional Opposing Streams", "description": "Opposing groups meeting head-on; triggers counterflow warnings."},
        {"id": "surge_gate", "name": "Ingress Gate Surge", "description": "Rapid crowd accumulation at north entrance exceeding 3.0 p/m² critical threshold."},
    ]
    return {
        "calibration": calib_preset.model_dump(),
        "venue": venue_model.model_dump(),
        "scenarios": scenarios,
        "heatmap_modes": [m.value for m in HeatmapMode],
    }


@router.post("/calibration", response_model=CalibrationResult)
async def configure_camera_calibration(config: CalibrationConfig):
    """Calculates and validates 4-point homography calibration for ground-plane mapping."""
    pipeline = get_default_pipeline()
    result = pipeline.calibration.calibrate(config)
    if not result.valid:
        raise HTTPException(status_code=400, detail=result.message)
    # Update pipeline engines with new calibration
    pipeline.perspective.calib = pipeline.calibration
    pipeline.detector.calib = pipeline.calibration
    pipeline.tracker.calib = pipeline.calibration
    pipeline.density_engine.calib = pipeline.calibration
    pipeline.movement_engine.calib = pipeline.calibration
    pipeline.synthetic_engine.calib = pipeline.calibration
    return result


@router.post("/video/upload")
async def upload_camera_video(
    file: UploadFile = File(...),
):
    """Uploads a conventional CCTV video file for VCIE spatial processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    allowed_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported video format: {ext}. Allowed: {allowed_exts}")

    job_id = f"cg-upload-{uuid.uuid4().hex[:8]}"
    saved_path = _UPLOAD_DIR / f"{job_id}{ext}"

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Probe video metadata using OpenCV
    cap = cv2.VideoCapture(str(saved_path))
    if not cap.isOpened():
        os.remove(saved_path)
        raise HTTPException(status_code=400, detail="Failed to decode uploaded video stream.")

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_s = round(frame_count / max(1.0, fps), 2)
    cap.release()

    return {
        "job_id": job_id,
        "filename": file.filename,
        "saved_path": str(saved_path),
        "video_metadata": {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frame_count,
            "duration_seconds": duration_s,
        },
        "message": "Video successfully uploaded and validated.",
    }


def _run_background_video_analysis(
    job_id: str,
    video_path: str,
    pipeline: VirtualCrowdIntelligencePipeline,
    max_frames: int,
):
    """Worker function for asynchronous batch video analysis."""
    try:
        def on_progress(summary: AnalysisJobSummary):
            summary.job_id = job_id
            _active_jobs[job_id] = summary

        pipeline.process_video_file(video_path, max_frames=max_frames, progress_callback=on_progress)

        summary = _active_jobs.get(job_id)
        if summary:
            summary.status = "completed"
            summary.progress_pct = 100.0
            summary.completed_at = str(time.time())
            _active_jobs[job_id] = summary
    except Exception as e:
        logger.exception("Error during background video analysis for job %s: %s", job_id, str(e))
        _active_jobs[job_id] = AnalysisJobSummary(
            job_id=job_id,
            status="failed",
            error=str(e),
            created_at=str(time.time()),
        )


@router.post("/analysis/start")
async def start_video_analysis(
    background_tasks: BackgroundTasks,
    video_path: Optional[str] = Form(None),
    job_id: Optional[str] = Form(None),
    frame_stride: int = Form(2),
    detection_confidence: float = Form(0.35),
    heatmap_mode: str = Form("gaussian"),
    max_frames: int = Form(250),
):
    """Initiates an asynchronous non-blocking video analysis job."""
    target_job_id = job_id or f"cg-job-{uuid.uuid4().hex[:8]}"

    # Use uploaded file or generate sample demonstration video
    if not video_path or not os.path.exists(video_path):
        sample_path = str(_UPLOAD_DIR / f"synthetic_sample_{target_job_id}.mp4")
        temp_pipeline = VirtualCrowdIntelligencePipeline()
        temp_pipeline.synthetic_engine.export_sample_video(sample_path, num_frames=120)
        video_path = sample_path

    # Instantiate dedicated pipeline for this analysis job
    cfg = VideoProcessingConfig(
        frame_stride=frame_stride,
        detection_confidence=detection_confidence,
        heatmap_mode=HeatmapMode(heatmap_mode) if heatmap_mode in [m.value for m in HeatmapMode] else HeatmapMode.GAUSSIAN,
    )
    job_pipeline = VirtualCrowdIntelligencePipeline(processing_config=cfg)
    _job_pipelines[target_job_id] = job_pipeline

    initial_summary = AnalysisJobSummary(
        job_id=target_job_id,
        status="running",
        progress_pct=0.0,
        current_frame=0,
        total_frames=max_frames,
        created_at=str(time.time()),
    )
    _active_jobs[target_job_id] = initial_summary

    background_tasks.add_task(
        _run_background_video_analysis,
        target_job_id,
        video_path,
        job_pipeline,
        max_frames,
    )

    return {
        "job_id": target_job_id,
        "status": "running",
        "video_path": video_path,
        "message": "Analysis job launched in background without blocking event loop.",
    }


@router.get("/analysis/{job_id}", response_model=AnalysisJobSummary)
async def get_analysis_status(job_id: str):
    """Retrieves current execution progress and telemetry for an analysis job."""
    if job_id == "live" or job_id == "default":
        p = get_default_pipeline()
        return AnalysisJobSummary(
            job_id="live",
            status="completed",
            progress_pct=100.0,
            current_frame=p._frame_count,
            total_frames=p._frame_count,
            fps=p.fps,
            latest_metrics=p.latest_result,
            created_at=str(p._start_time),
        )

    summary = _active_jobs.get(job_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Analysis job {job_id} not found.")
    return summary


@router.post("/simulation/step")
async def step_simulation(
    scenario: str = Query("plaza_normal", description="plaza_normal | bottleneck | counterflow | surge_gate"),
    mode: str = Query("gaussian", description="gaussian | point | zone | movement"),
    sigma: float = Query(28.0, ge=5.0, le=80.0),
):
    """Steps the deterministic synthetic simulation and returns complete frame telemetry."""
    pipeline = get_default_pipeline()
    if mode in [m.value for m in HeatmapMode]:
        pipeline.config.heatmap_mode = HeatmapMode(mode)
    pipeline.config.kde_bandwidth_sigma = sigma

    res = pipeline.step_synthetic(scenario=scenario)
    return res


@router.post("/simulation/reset")
async def reset_simulation(
    scenario: str = Query("plaza_normal"),
):
    """Resets the synthetic demonstration scenario to initial state."""
    pipeline = get_default_pipeline()
    pipeline.synthetic_engine._init_scenario(scenario)
    pipeline.tracker.tracks.clear()
    res = pipeline.step_synthetic(scenario=scenario)
    return {
        "scenario": scenario,
        "message": f"Simulation reset to scenario: {scenario}",
        "metrics": res,
    }


@router.get("/analysis/{job_id}/frame")
async def get_camera_frame_image(job_id: str):
    """Returns the latest camera perspective frame with bounding boxes as a JPEG image."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline:
        pipeline = get_default_pipeline()

    frame = pipeline.latest_camera_frame
    if frame is None:
        raise HTTPException(status_code=404, detail="No frame processed yet.")

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode frame.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@router.get("/analysis/{job_id}/birdseye")
async def get_birdseye_frame_image(job_id: str):
    """Returns the latest perspective-warped bird's-eye view with metric grid as a JPEG image."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline:
        pipeline = get_default_pipeline()

    frame = pipeline.latest_birdseye_frame
    if frame is None:
        raise HTTPException(status_code=404, detail="No bird's-eye frame available.")

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode bird's-eye frame.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@router.get("/analysis/{job_id}/heatmap")
async def get_heatmap_frame_image(job_id: str):
    """Returns the latest Gaussian KDE crowd density heatmap overlay as a JPEG/PNG image."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline:
        pipeline = get_default_pipeline()

    frame = pipeline.latest_heatmap_frame
    if frame is None:
        raise HTTPException(status_code=404, detail="No heatmap frame available.")

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode heatmap frame.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@router.get("/analysis/{job_id}/movement")
async def get_movement_frame_image(job_id: str):
    """Returns the latest movement vectors view as a JPEG image."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline:
        pipeline = get_default_pipeline()

    frame = pipeline.latest_movement_frame
    if frame is None:
        raise HTTPException(status_code=404, detail="No movement frame available.")

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode movement frame.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@router.get("/analysis/{job_id}/digitaltwin")
async def get_digital_twin_frame_image(job_id: str):
    """Returns the composite digital twin representation of the venue as a JPEG image."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline:
        pipeline = get_default_pipeline()

    frame = pipeline.latest_digital_twin_frame
    if frame is None:
        raise HTTPException(status_code=404, detail="No digital twin frame available.")

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode digital twin frame.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@router.get("/analysis/{job_id}/tracks")
async def get_active_tracks(job_id: str):
    """Returns current active track trajectories, positions, velocities, and alerts."""
    pipeline = _job_pipelines.get(job_id) if job_id != "live" else get_default_pipeline()
    if not pipeline or not pipeline.latest_result:
        raise HTTPException(status_code=404, detail="No track telemetry available.")

    res = pipeline.latest_result
    return {
        "job_id": job_id,
        "frame_idx": res.frame_idx,
        "timestamp_s": res.timestamp_s,
        "active_tracks_count": res.active_tracks_count,
        "tracks": [t.model_dump() for t in res.tracks],
        "movement_vectors": [v.model_dump() for v in res.movement_vectors],
        "zone_metrics": [z.model_dump() for z in res.zone_metrics],
        "peak_density_per_sq_meter": res.peak_density_per_sq_meter,
        "alerts": [a.model_dump() for a in res.alerts],
    }
