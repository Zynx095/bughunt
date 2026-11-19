"""Video / image ingestion: detect people, track them, assign them to camera zones and measure flow.

Camera zones are polygons in *normalised* image coordinates (0-1), so one layout works at any
resolution. Each camera zone may name the ``venue_zone`` it observes and the fraction of that
venue zone it covers, which lets a camera reading feed the venue-wide assessment.

Counting rules:
  * Instantaneous occupancy = confirmed tracks whose foot point is inside the zone in that frame.
  * The reported current count is the median over the last few processed frames (suppresses flicker).
  * Unique people = distinct track ids; repeated detections of one person never add up.
  * A frame where the detector raised an error is a *detection failure*, not an empty frame.
"""
from __future__ import annotations

import base64
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .calibration import CameraCalibrationEngine
from .crowd_flow import direction_histogram, flow_stats, track_velocities, zone_flow_stats
from .crowd_tracking import TrackHistory
from .density_estimator import Observation, assess_reading, occlusion_corrected
from .schemas import CalibrationConfig, CalibrationPoint, CalibrationQuad
from .zone_manager import ZoneManager

VIDEO_MAGIC = ((4, b"ftyp"), (0, b"\x1a\x45\xdf\xa3"), (0, b"RIFF"))
DEFAULT_TARGET_FPS = 5.0


def sniff_media(head: bytes) -> str | None:
    """Return 'image' or 'video' from magic bytes (never from the client's declared type)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp":
        return "video"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video"  # Matroska / WebM
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video"
    return None


def _camera_zones(layout: dict[str, Any]) -> ZoneManager:
    return ZoneManager.from_config(layout["zones"])


def _encode_jpeg(frame: np.ndarray, max_w: int = 720, quality: int = 72) -> tuple[str, int, int]:
    import cv2  # noqa: PLC0415

    h, w = frame.shape[:2]
    if w > max_w:
        frame = cv2.resize(frame, (max_w, int(h * max_w / w)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii"), frame.shape[1], frame.shape[0]


def scaled_default_calibration(frame_w: int, frame_h: int) -> CalibrationConfig:
    """The demo calibration preset (defined for 1280x720) rescaled to this frame size. It is a *placeholder*
    ground plane, not a calibration of the real camera; results say so until an operator calibrates."""
    base = CameraCalibrationEngine.get_default_calibration()
    sx, sy = frame_w / 1280.0, frame_h / 720.0
    q = base.source_points
    quad = CalibrationQuad(**{k: CalibrationPoint(x=getattr(q, k).x * sx, y=getattr(q, k).y * sy)
                              for k in ("top_left", "top_right", "bottom_right", "bottom_left")})
    return base.model_copy(update={"source_points": quad})


def _telemetry(res) -> dict[str, Any]:
    return {"frame_idx": res.frame_idx, "timestamp_s": res.timestamp_s, "total_detected": res.total_detected,
            "active_tracks": res.active_tracks_count, "peak_density": res.peak_density_per_sq_meter,
            "mean_density": res.mean_density_per_sq_meter, "high_density_area_m2": res.high_density_area_sq_meters,
            "latency_ms": res.processing_latency_ms, "detection_failed": res.detection_failed,
            "zone_metrics": [z.model_dump(mode="json") for z in res.zone_metrics],
            "alerts": [a.model_dump(mode="json") for a in res.alerts],
            "movement_vectors": len(res.movement_vectors)}


def analyse_media(path: str | Path, kind: str, layout: dict[str, Any], *, calibration: CalibrationConfig | None = None,
                  calibration_source: str = "default preset", target_fps: float = DEFAULT_TARGET_FPS,
                  max_seconds: float = 30.0, max_frames: int = 180, keyframes: int = 8,
                  thresholds: dict[str, float] | None = None, heatmap_mode: str = "gaussian", sigma: float = 28.0,
                  progress=None) -> dict[str, Any]:
    """Run recorded footage through the single VCIE pipeline and aggregate it for CROWDGUARD.

    Per sampled frame: detection (crowd_detection) -> ByteTrack identity -> ground-plane projection and
    Kalman kinematics -> KDE density -> bird's-eye zones and movement alerts. Key frames also render the
    five synchronised views (camera, bird's-eye, heatmap, movement, digital twin).
    """
    import cv2  # noqa: PLC0415

    from .pipeline import VirtualCrowdIntelligencePipeline  # noqa: PLC0415 - heavy, imported on use

    started = time.perf_counter()
    zm = _camera_zones(layout)
    zones = {z.id: z for z in zm.zones}
    warnings: list[str] = []
    mpp = layout.get("meters_per_pixel")

    frames: list[tuple[float, np.ndarray]] = []
    fps = None
    if kind == "image":
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            return {"ok": False, "error": "decode_failed", "message": "Image could not be decoded"}
        frames.append((0.0, img))
    else:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return {"ok": False, "error": "decode_failed", "message": "Video could not be opened (codec not supported by OpenCV?)"}
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not fps or fps <= 0 or fps > 240 or math.isnan(fps):
            warnings.append("Video reports no valid frame rate; assuming 25 fps for timing")
            fps = 25.0
        stride = max(1, int(round(fps / target_fps)))
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps
            if t > max_seconds or len(frames) >= max_frames:
                warnings.append(f"Analysis truncated at {min(t, max_seconds):.1f} s / {len(frames)} frames (limits)")
                break
            if idx % stride == 0:
                frames.append((t, frame))
            idx += 1
        cap.release()
        if not frames:
            return {"ok": False, "error": "decode_failed", "message": "No frames could be read from the video"}

    # The pipeline processes frames at most 1280 px wide; all image-space coordinates refer to that size.
    H0, W0 = frames[0][1].shape[:2]
    scale = min(1.0, 1280.0 / W0)
    W, H = int(round(W0 * scale)), int(round(H0 * scale))
    if calibration is None:
        calibration, calibration_source = scaled_default_calibration(W, H), "default preset (not calibrated for this camera)"
    from .schemas import HeatmapMode, VideoProcessingConfig  # noqa: PLC0415

    cfg = VideoProcessingConfig(frame_stride=1, detection_confidence=0.3, kde_bandwidth_sigma=sigma,
                                heatmap_mode=HeatmapMode(heatmap_mode) if heatmap_mode in [m.value for m in HeatmapMode] else HeatmapMode.GAUSSIAN)
    pipeline = VirtualCrowdIntelligencePipeline(calibration_config=calibration, processing_config=cfg,
                                                identity_tracking=(kind == "video"))
    if not pipeline.calibration.is_valid:
        return {"ok": False, "error": "invalid_calibration", "message": pipeline.calibration.result.message if pipeline.calibration.result else "invalid"}
    detector_status = {**pipeline.detector.status, "backend": pipeline.detector.backend}

    history = TrackHistory()
    per_frame: list[dict[str, Any]] = []
    det_errors = 0
    confs: list[float] = []
    key_idx = set(np.linspace(0, len(frames) - 1, num=min(keyframes, len(frames)), dtype=int).tolist())
    key_out = []
    ground_speeds: list[float] = []
    for i, (t, frame) in enumerate(frames):
        render = i in key_idx
        res = pipeline.process_frame(frame, frame_idx=i, timestamp_s=t, render=render,
                                     source_kind="image" if kind == "image" else "recorded_video")
        row: dict[str, Any] = {"t": round(t, 3), "frame_index": i, "peak_density": res.peak_density_per_sq_meter,
                               "ground_tracks": res.active_tracks_count}
        if res.detection_failed:
            det_errors += 1
            row.update(status="detector_error", detections=None, counts=None)
            per_frame.append(row)
            continue
        raw = pipeline.last_raw_boxes
        confs.extend(b.confidence for b in raw)
        if kind == "video":
            objs = [(o.track_id, o.box, o.confidence, o.confirmed) for o in pipeline.last_identity_objects]
        else:
            objs = [(None, (b.x1, b.y1, b.x2, b.y2), b.confidence, True) for b in raw]
        ground_speeds.extend(tr.speed_mps for tr in res.tracks)
        counts = {z: 0 for z in zones}
        boxes = []
        for tid, box, conf, confirmed in objs:
            fx, fy = (box[0] + box[2]) / 2 / W, box[3] / H
            zid = zm.assign((fx, fy))
            if tid is not None:
                history.add(tid, t, (box[0] + box[2]) / 2, box[3], zid)
            if confirmed and zid:
                counts[zid] += 1
            boxes.append({"id": tid, "box": [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)],
                          "conf": round(float(conf), 3), "zone": zid, "confirmed": confirmed})
        row.update(status="ok", detections=len(raw), counts=counts, tracked=len(objs))
        per_frame.append(row)
        if render:
            proc = frame if scale == 1.0 else cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
            img, kw, kh = _encode_jpeg(proc, max_w=640)
            key_out.append({"t": round(t, 2), "frame_index": i, "image": img, "width": kw, "height": kh, "boxes": boxes,
                            "views": pipeline.render_bundle(max_width=480, quality=68), "telemetry": _telemetry(res)})
        if progress:
            progress(i + 1, len(frames))

    ok_frames = [r for r in per_frame if r["status"] == "ok"]
    velocities = track_velocities(history, meters_per_pixel=mpp) if kind == "video" else []
    stationary = 0.15 if mpp else 0.02 * W  # px/s threshold: 2% of frame width per second
    zflow = zone_flow_stats(velocities, stationary)
    frag = history.fragmentation() if kind == "video" else None
    det_conf = float(np.mean(confs)) if confs else None
    zone_results, observations = [], []
    for zid, z in zones.items():
        series = [r["counts"][zid] if r["status"] == "ok" else None for r in per_frame]
        valid = [v for v in series if v is not None]
        recent = valid[-5:]
        current = int(np.median(recent)) if recent else None
        status = "ok" if current is not None else "detector_error"
        obs = Observation(zone_id=zid, t=per_frame[-1]["t"], feed_status=status, observed_count=current,
                          detector_confidence=det_conf if det_conf is not None else (0.6 if current == 0 else None),
                          tracking_stability=(1 - frag) if frag is not None else None, source=kind, value_kind="measured")
        reading = assess_reading(z, obs, None, thresholds)
        zone_results.append({
            "zone_id": zid, "name": z.name, "venue_zone": z.venue_zone, "coverage": z.extra.get("coverage") if z.extra else None,
            "area_m2": z.area_m2, "safe_capacity": z.safe_capacity,
            "current_observed": current, "peak_observed": max(valid) if valid else None,
            "mean_observed": round(float(np.mean(valid)), 2) if valid else None,
            "unique_people": history.unique_per_zone().get(zid, 0) if kind == "video" else current,
            "reading": reading, "flow": zflow.get(zid, flow_stats([], stationary)),
            "series": [{"t": r["t"], "count": r["counts"][zid] if r["status"] == "ok" else None} for r in per_frame],
        })
        observations.append({"camera_zone": zid, "venue_zone": z.venue_zone, "observed_count": current,
                             "feed_status": status, "detector_confidence": det_conf,
                             "tracking_stability": (1 - frag) if frag is not None else None})
    total_series = [{"t": r["t"], "detections": r.get("detections"), "tracked": r.get("tracked"),
                     "peak_density": r.get("peak_density"), "ground_tracks": r.get("ground_tracks")} for r in per_frame]
    trails = {}
    for tid, pts in history.points.items():
        if len(pts) >= 2:
            trails[str(tid)] = [[round(p.x / W, 4), round(p.y / H, 4)] for p in pts[-25:]]
    ok_ratio = len(ok_frames) / len(per_frame) if per_frame else 0
    quality = {
        "frames_processed": len(per_frame), "frames_ok": len(ok_frames), "frames_detector_error": det_errors,
        "mean_detection_confidence": round(det_conf, 3) if det_conf is not None else None,
        "track_fragmentation": round(frag, 3) if frag is not None else None,
        "unique_tracks": len(history.unique_ids()) if kind == "video" else None,
        "processed_fps": round(fps / max(1, int(round(fps / target_fps))), 2) if fps else None,
        "duration_s": per_frame[-1]["t"] if per_frame else 0, "usable": ok_ratio >= 0.5,
    }
    if det_errors:
        warnings.append(f"{det_errors} frame(s) had detection failures: treated as unknown, not as empty")
    if detector_status.get("backend") == "hog":
        warnings.append("Using the OpenCV HOG fallback detector: counts are biased low for dense or occluded crowds")
    if kind == "image":
        warnings.append("Single image: no tracking or movement analysis is possible; counts are per-detection")
    if not mpp and kind != "image":
        warnings.append("No metres-per-pixel calibration for the camera zones: their speeds are in pixels per second")
    if calibration_source.startswith("default"):
        warnings.append("Bird's-eye view uses the default demo calibration rescaled to this frame: calibrate the four ground points for metric densities and speeds")
    last_count = ok_frames[-5:]
    whole = occlusion_corrected(int(np.median([r["tracked"] if r.get("tracked") is not None else r["detections"] for r in last_count])) if last_count else 0,
                                sum(z.area_m2 for z in zones.values()))
    return {
        "ok": True, "kind": kind, "source_kind": "image" if kind == "image" else "recorded_video",
        "detector": detector_status, "tracker": {"tracker": pipeline.identity_tracker_info.get("tracker") if kind == "video" else "not applicable (single image)",
                                                 "kinematics": "ground-plane Kalman filter (tracking.py)"},
        "calibration": {"source": calibration_source, "config": calibration.model_dump(mode="json"),
                        "result": pipeline.calibration.result.model_dump(mode="json") if pipeline.calibration.result else None},
        "frame_size": [W, H], "layout": layout, "zones": zone_results, "observations": observations,
        "totals": {"series": total_series, "frame_estimate": whole,
                   "unique_people": len(history.unique_ids()) if kind == "video" else (ok_frames[-1]["detections"] if ok_frames else None),
                   "transitions": history.transitions() if kind == "video" else {}},
        "flow": {"unit": "m/s" if mpp else "px/s", "overall": flow_stats(velocities, stationary),
                 "direction_histogram": direction_histogram(velocities, min_speed=stationary), "tracks": velocities[:300],
                 "ground_plane": {"unit": "m/s", "calibrated": not calibration_source.startswith("default"),
                                  "mean_speed": round(float(np.mean(ground_speeds)), 3) if ground_speeds else None}},
        "keyframes": key_out, "trails": trails, "quality": quality, "warnings": warnings,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "labels": {"counts": "observed = people the detector saw; estimate = occlusion-corrected with interval; neither is ground truth"},
    }


def make_sample_clip(out_path: str | Path, seconds: float = 5.0, fps: int = 15) -> dict[str, Any]:
    """Build a short test clip by panning across the Ultralytics sample photo (people really detected,
    motion artificial). Returns provenance. Raises FileNotFoundError if the asset is unavailable."""
    import cv2  # noqa: PLC0415

    try:
        import ultralytics  # noqa: PLC0415

        src = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    except Exception as exc:  # noqa: BLE001
        raise FileNotFoundError("ultralytics sample assets unavailable") from exc
    img = cv2.imread(str(src))
    if img is None:
        raise FileNotFoundError(str(src))
    h, w = img.shape[:2]
    crop_w, crop_h = int(w * 0.78), int(h * 0.62)
    y0 = h - crop_h - int(h * 0.04)
    n = int(seconds * fps)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, int(640 * crop_h / crop_w)))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an MP4 writer")
    for i in range(n):
        x0 = int((w - crop_w) * (0.5 - 0.5 * math.cos(math.pi * i / max(1, n - 1))))
        frame = img[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cv2.resize(frame, (640, int(640 * crop_h / crop_w))))
    writer.release()
    return {"source_image": "ultralytics/assets/bus.jpg", "frames": n, "fps": fps,
            "label": "TEST CLIP: camera pan synthesised from a single sample photo. People are real detections; their apparent motion is artificial."}


__all__ = ["analyse_media", "make_sample_clip", "sniff_media", "scaled_default_calibration"]
