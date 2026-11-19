"""Person detection behind one interface, with honest capability reporting.

Backends, in order of preference:
  1. ``yolo``  – Ultralytics YOLO (person class only) from a weights file that must already exist
                 locally. Nothing is ever downloaded: ``YOLO_OFFLINE`` is forced before import.
  2. ``hog``   – OpenCV's built-in HOG + linear SVM pedestrian detector (no weights needed;
                 much weaker, especially for dense or partially occluded crowds).
If neither is usable the detector reports ``available = False`` and callers must treat every
frame as a *detection failure*, never as an empty scene.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("crowdguard.detection")

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
WEIGHT_NAMES = ("yolo11n.pt", "yolov8n.pt", "yolo11s.pt", "yolov8s.pt")


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    label: str = "person"

    @property
    def foot(self) -> tuple[float, float]:
        """Bottom-centre of the box: the ground contact point used for zone assignment."""
        return ((self.x1 + self.x2) / 2.0, self.y2)

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


class DetectorUnavailable(RuntimeError):
    pass


class PersonDetector(Protocol):
    name: str

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...


def candidate_weight_paths(configured: str | None = None) -> list[Path]:
    paths: list[Path] = []
    if configured:
        paths.append(Path(configured).expanduser())
    env = os.getenv("CROWDGUARD_YOLO_WEIGHTS")
    if env:
        paths.append(Path(env).expanduser())
    for base in (BACKEND_ROOT / "models", BACKEND_ROOT.parent, Path.home()):
        paths.extend(base / n for n in WEIGHT_NAMES)
    return list(dict.fromkeys(paths))


def find_weights(configured: str | None = None) -> tuple[Path | None, list[str]]:
    searched = candidate_weight_paths(configured)
    for p in searched:
        try:
            if p.is_file() and p.stat().st_size > 1_000_000:
                return p, [str(s) for s in searched]
        except OSError:
            continue
    return None, [str(s) for s in searched]


class YoloPersonDetector:
    name = "yolo"

    def __init__(self, weights: Path, conf: float = 0.25, imgsz: int = 640) -> None:
        self.weights = Path(weights)
        self.conf = conf
        self.imgsz = imgsz
        self._model = None
        self._lock = threading.Lock()
        self.model_name = self.weights.name

    def _load(self):
        if self._model is None:
            os.environ["YOLO_OFFLINE"] = "true"  # no downloads, no telemetry
            try:
                from ultralytics import YOLO  # noqa: PLC0415 - heavy optional import
            except Exception as exc:  # noqa: BLE001
                raise DetectorUnavailable(f"ultralytics import failed: {exc}") from exc
            if not self.weights.is_file():
                raise DetectorUnavailable(f"weights not found: {self.weights}")
            self._model = YOLO(str(self.weights))
        return self._model

    def verify(self) -> dict[str, Any]:
        """Load the model and run one inference on a blank frame to prove it works."""
        with self._lock:
            model = self._load()
            model.predict(np.zeros((64, 64, 3), dtype=np.uint8), classes=[0], verbose=False, imgsz=64)
        names = getattr(model, "names", {}) or {}
        return {"classes": len(names), "person_class": names.get(0)}

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        with self._lock:
            model = self._load()
            res = model.predict(frame_bgr, classes=[0], conf=self.conf, imgsz=self.imgsz, verbose=False)
        out: list[Detection] = []
        if not res:
            return out
        boxes = res[0].boxes
        if boxes is None or len(boxes) == 0:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        for (x1, y1, x2, y2), c in zip(xyxy, confs):
            out.append(Detection(float(x1), float(y1), float(x2), float(y2), float(c)))
        return out


class HogPersonDetector:
    """OpenCV HOG pedestrian detector. Upright, fairly large people only; weak in dense crowds."""

    name = "hog"

    def __init__(self, min_conf: float = 0.3) -> None:
        import cv2  # noqa: PLC0415

        self._cv2 = cv2
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.min_conf = min_conf
        self.model_name = "OpenCV HOG + linear SVM (Dalal-Triggs)"

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        cv2 = self._cv2
        h, w = frame_bgr.shape[:2]
        scale = 1.0
        if w > 800:
            scale = 800.0 / w
            frame_bgr = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)))
        rects, weights = self.hog.detectMultiScale(frame_bgr, winStride=(8, 8), padding=(8, 8), scale=1.05)
        out = []
        for (x, y, rw, rh), wt in zip(rects, np.ravel(weights) if len(rects) else []):
            conf = float(1 / (1 + np.exp(-float(wt))))  # squash SVM margin to 0-1 (not a calibrated probability)
            if conf >= self.min_conf:
                out.append(Detection(x / scale, y / scale, (x + rw) / scale, (y + rh) / scale, conf))
        return out


class _Registry:
    """Process-wide detector cache (loading YOLO takes seconds)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[PersonDetector | None, dict[str, Any]]] = {}

    def get(self, preference: str = "auto", weights: str | None = None, verify: bool = True):
        key = f"{preference}|{weights}"
        with self._lock:
            if key not in self._cache:
                self._cache[key] = _build(preference, weights, verify)
            return self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


def _build(preference: str, weights: str | None, verify: bool) -> tuple[PersonDetector | None, dict[str, Any]]:
    status: dict[str, Any] = {"preference": preference, "backend": "none", "available": False, "verified": False,
                              "attempts": []}
    if preference in ("auto", "yolo"):
        path, searched = find_weights(weights)
        status["weights_searched"] = searched
        if path is None:
            status["attempts"].append({"backend": "yolo", "ok": False, "reason": "no YOLO weights file found locally (downloads are disabled)"})
        else:
            det = YoloPersonDetector(path)
            try:
                info = det.verify() if verify else {}
                status.update(backend="yolo", available=True, verified=verify, weights_path=str(path),
                              model=det.model_name, weights_bytes=path.stat().st_size, **info)
                status["attempts"].append({"backend": "yolo", "ok": True})
                return det, status
            except Exception as exc:  # noqa: BLE001
                status["attempts"].append({"backend": "yolo", "ok": False, "reason": f"{type(exc).__name__}: {exc}"})
                log.warning("YOLO unavailable: %s", exc)
    if preference in ("auto", "hog"):
        try:
            det = HogPersonDetector()
            if verify:
                det.detect(np.zeros((128, 64, 3), dtype=np.uint8))
            status.update(backend="hog", available=True, verified=verify, model=det.model_name,
                          limitation="HOG misses small, seated and occluded people; counts will be biased low in dense crowds")
            status["attempts"].append({"backend": "hog", "ok": True})
            return det, status
        except Exception as exc:  # noqa: BLE001
            status["attempts"].append({"backend": "hog", "ok": False, "reason": f"{type(exc).__name__}: {exc}"})
    status["reason"] = "no person detector could be initialised"
    return None, status


DETECTORS = _Registry()


def get_detector(preference: str = "auto", weights: str | None = None) -> tuple[PersonDetector | None, dict[str, Any]]:
    return DETECTORS.get(preference, weights)
