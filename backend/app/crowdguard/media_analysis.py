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

from .crowd_flow import direction_histogram, flow_stats, track_velocities, zone_flow_stats
from .crowd_tracking import IoUTracker, TrackHistory, build_tracker
from .density_estimator import Observation, assess_reading, occlusion_corrected
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


def analyse_media(path: str | Path, kind: str, layout: dict[str, Any], detector, detector_status: dict[str, Any], *,
                  tracker_preference: str = "auto", target_fps: float = DEFAULT_TARGET_FPS, max_seconds: float = 30.0,
                  max_frames: int = 180, keyframes: int = 6, thresholds: dict[str, float] | None = None,
                  progress=None) -> dict[str, Any]:
    import cv2  # noqa: PLC0415

    started = time.perf_counter()
    zm = _camera_zones(layout)
    zones = {z.id: z for z in zm.zones}
    warnings: list[str] = []
    mpp = layout.get("meters_per_pixel")
    speed_unit = "m/s" if mpp else "px/s"

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
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
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
        if total and idx < total * 0.5 and not any("truncated" in w for w in warnings):
            warnings.append("Fewer frames decoded than the container reports; the file may be damaged")

    processed_fps = (fps / max(1, int(round(fps / target_fps)))) if fps else None
    tracker, tracker_info = (None, {"tracker": "not applicable (single image)"}) if kind == "image" else build_tracker(
        tracker_preference, frame_rate=processed_fps or target_fps)
    history = TrackHistory()
    per_frame: list[dict[str, Any]] = []
    det_errors = 0
    confs: list[float] = []
    key_idx = set(np.linspace(0, len(frames) - 1, num=min(keyframes, len(frames)), dtype=int).tolist())
    key_out = []
    H = W = None
    for i, (t, frame) in enumerate(frames):
        H, W = frame.shape[:2]
        row: dict[str, Any] = {"t": round(t, 3), "frame_index": i}
        if detector is None:
            det_errors += 1
            row.update(status="detector_error", detections=None, counts=None)
            per_frame.append(row)
            continue
        try:
            dets = detector.detect(frame)
        except Exception as exc:  # noqa: BLE001 - a failed frame is recorded, never treated as empty
            det_errors += 1
            row.update(status="detector_error", error=f"{type(exc).__name__}: {exc}", detections=None, counts=None)
            per_frame.append(row)
            continue
        confs.extend(d.confidence for d in dets)
        if tracker is not None:
            tracked = tracker.update(dets, t)
            objs = [(o.track_id, o.box, o.confidence, o.confirmed) for o in tracked]
        else:
            objs = [(None, d.xyxy, d.confidence, True) for d in dets]
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
                          "conf": round(conf, 3), "zone": zid, "confirmed": confirmed})
        row.update(status="ok", detections=len(dets), counts=counts, tracked=len(objs))
        per_frame.append(row)
        if i in key_idx:
            img, kw, kh = _encode_jpeg(frame)
            key_out.append({"t": round(t, 2), "frame_index": i, "image": img, "width": kw, "height": kh, "boxes": boxes})
        if progress:
            progress(i + 1, len(frames))

    ok_frames = [r for r in per_frame if r["status"] == "ok"]
    velocities = track_velocities(history, meters_per_pixel=mpp) if tracker is not None else []
    stationary = 0.15 if mpp else 0.02 * (W or 1)  # px/s threshold: 2% of frame width per second
    zflow = zone_flow_stats(velocities, stationary)
    frag = history.fragmentation() if tracker is not None else None
    det_conf = float(np.mean(confs)) if confs else None
    zone_results = []
    observations = []
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
            "unique_people": history.unique_per_zone().get(zid, 0) if tracker is not None else current,
            "reading": reading, "flow": zflow.get(zid, flow_stats([], stationary)),
            "series": [{"t": r["t"], "count": r["counts"][zid] if r["status"] == "ok" else None} for r in per_frame],
        })
        observations.append({"camera_zone": zid, "venue_zone": z.venue_zone, "observed_count": current,
                             "feed_status": status, "detector_confidence": det_conf,
                             "tracking_stability": (1 - frag) if frag is not None else None})
    total_series = [{"t": r["t"], "detections": r.get("detections"), "tracked": r.get("tracked")} for r in per_frame]
    trails = {}
    for tid, pts in history.points.items():
        if len(pts) >= 2 and W and H:
            trails[str(tid)] = [[round(p.x / W, 4), round(p.y / H, 4)] for p in pts[-25:]]
    ok_ratio = len(ok_frames) / len(per_frame) if per_frame else 0
    quality = {
        "frames_processed": len(per_frame), "frames_ok": len(ok_frames), "frames_detector_error": det_errors,
        "mean_detection_confidence": round(det_conf, 3) if det_conf is not None else None,
        "track_fragmentation": round(frag, 3) if frag is not None else None,
        "unique_tracks": len(history.unique_ids()) if tracker is not None else None,
        "processed_fps": round(processed_fps, 2) if processed_fps else None, "duration_s": per_frame[-1]["t"] if per_frame else 0,
        "usable": ok_ratio >= 0.5,
    }
    if det_errors:
        warnings.append(f"{det_errors} frame(s) had detection failures: treated as unknown, not as empty")
    if detector_status.get("backend") == "hog":
        warnings.append("Using the OpenCV HOG fallback detector: counts are biased low for dense or occluded crowds")
    if kind == "image":
        warnings.append("Single image: no tracking or movement analysis is possible; counts are per-detection")
    if not mpp and kind != "image":
        warnings.append("No metres-per-pixel calibration: speeds are in pixels per second")
    whole = occlusion_corrected(int(np.median([r["tracked"] if r.get("tracked") is not None else r["detections"] for r in ok_frames[-5:]])) if ok_frames else 0,
                                sum(z.area_m2 for z in zones.values()))
    return {
        "ok": True, "kind": kind, "detector": detector_status, "tracker": tracker_info,
        "frame_size": [W, H], "layout": layout, "zones": zone_results, "observations": observations,
        "totals": {"series": total_series, "frame_estimate": whole,
                   "unique_people": len(history.unique_ids()) if tracker is not None else (ok_frames[-1]["detections"] if ok_frames else None),
                   "transitions": history.transitions() if tracker is not None else {}},
        "flow": {"unit": speed_unit, "overall": flow_stats(velocities, stationary), "direction_histogram": direction_histogram(velocities, min_speed=stationary),
                 "tracks": velocities[:300]},
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


__all__ = ["analyse_media", "make_sample_clip", "sniff_media", "IoUTracker"]
