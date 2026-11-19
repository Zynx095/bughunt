"""Frame sources for live monitoring: local cameras, RTSP/HTTP streams, recorded video, synthetic scenes.

Every source reports what it is (`kind`): "live_camera" for webcams and network streams,
"recorded_video" for files (played back at their own speed, never labelled live) and "synthetic" for
the simulated scene. `open()` raises `SourceError` with a specific code and an actionable message.
"""
from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import numpy as np

log = logging.getLogger("crowdguard.sources")

_PROBE_LOCK = threading.Lock()


class SourceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Frame:
    image: np.ndarray
    captured_at: float          # wall-clock seconds
    index: int                  # frame number from the source
    synthetic_boxes: Optional[list] = None  # synthetic source only: ground-truth person boxes


def _backends() -> list[tuple[str, int]]:
    import cv2  # noqa: PLC0415

    if platform.system() == "Windows":
        return [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)]
    if platform.system() == "Darwin":
        return [("avfoundation", cv2.CAP_AVFOUNDATION)]
    return [("v4l2", cv2.CAP_V4L2), ("any", cv2.CAP_ANY)]


def discover_cameras(max_index: int = 4, skip: set[int] | None = None) -> list[dict[str, Any]]:
    """Probe local camera indices. A camera that opens but returns no frame is reported as such
    (commonly: in use by another application, or blocked by OS privacy settings)."""
    import cv2  # noqa: PLC0415

    skip = skip or set()
    found = []
    with _PROBE_LOCK:
        for idx in range(max_index + 1):
            if idx in skip:
                found.append({"index": idx, "status": "in_use_by_crowdguard", "label": f"Camera {idx}"})
                continue
            for name, api in _backends():
                cap = cv2.VideoCapture(idx, api)
                try:
                    if not cap.isOpened():
                        continue
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        h, w = frame.shape[:2]
                        found.append({"index": idx, "backend": name, "status": "available", "width": w, "height": h,
                                      "label": f"Camera {idx} ({w}×{h})"})
                    else:
                        found.append({"index": idx, "backend": name, "status": "no_frames", "label": f"Camera {idx}",
                                      "detail": "Opens but returns no frames: it may be in use by another app or blocked by privacy settings"})
                    break
                finally:
                    cap.release()
    return found


class FrameSource:
    kind = "live_camera"
    live = True

    def __init__(self, label: str) -> None:
        self.label = label
        self.width = 0
        self.height = 0
        self.native_fps: Optional[float] = None
        self._index = 0

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "live": self.live, "label": self.label, "width": self.width, "height": self.height,
                "native_fps": self.native_fps}

    def open(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read(self) -> Optional[Frame]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    @property
    def reconnectable(self) -> bool:
        return self.kind == "live_camera"


class _CvSource(FrameSource):
    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.cap = None

    def _finish_open(self, cap) -> None:
        import cv2  # noqa: PLC0415

        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise SourceError("NO_FRAMES", f"{self.label} opened but delivered no frames. Close other apps using it, "
                              "check the OS camera privacy setting for desktop apps, then try again.")
        self.cap = cap
        self.height, self.width = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        self.native_fps = float(fps) if fps and 0 < fps < 240 else None
        self._first = frame

    def read(self) -> Optional[Frame]:
        if self.cap is None:
            return None
        if getattr(self, "_first", None) is not None:
            frame, self._first = self._first, None
        else:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                return None
        self._index += 1
        return Frame(frame, time.time(), self._index)

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class WebcamSource(_CvSource):
    kind = "live_camera"
    live = True

    def __init__(self, index: int, width: int = 1280, height: int = 720) -> None:
        super().__init__(f"Camera {index}")
        self.device_index = index
        self.req = (width, height)

    def open(self) -> None:
        import cv2  # noqa: PLC0415

        errors = []
        for name, api in _backends():
            cap = cv2.VideoCapture(self.device_index, api)
            if not cap.isOpened():
                errors.append(name)
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req[1])
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep the driver queue short: we want the newest frame
            try:
                self._finish_open(cap)
                self.backend = name
                self.label = f"Camera {self.device_index} ({self.width}×{self.height})"
                return
            except SourceError as exc:
                errors.append(f"{name}: {exc.code}")
        raise SourceError("CAMERA_UNAVAILABLE", f"Camera {self.device_index} could not be opened ({', '.join(errors)}). "
                          "It may be disconnected, in use by another application, or blocked by OS privacy settings.")


class StreamSource(_CvSource):
    kind = "live_camera"
    live = True

    def __init__(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("rtsp", "rtsps", "http", "https") or not parsed.hostname:
            raise SourceError("INVALID_STREAM", "Stream URL must be rtsp://, rtsps://, http:// or https:// with a host")
        safe = f"{parsed.scheme}://{parsed.hostname}{':' + str(parsed.port) if parsed.port else ''}{parsed.path}"
        super().__init__(f"Stream {safe}")  # credentials in the URL are never shown
        self.url = url

    def open(self) -> None:
        import cv2  # noqa: PLC0415

        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        if not cap.isOpened():
            cap.release()
            raise SourceError("STREAM_UNAVAILABLE", f"{self.label} could not be opened: check the address, credentials and network.")
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._finish_open(cap)


class VideoFileSource(_CvSource):
    """Plays a recorded file at its own frame rate (looping), so the pipeline sees it like a stream."""

    kind = "recorded_video"
    live = False

    def __init__(self, path: str | Path, label: str, loop: bool = True) -> None:
        super().__init__(f"Recording: {label}")
        self.path = str(path)
        self.loop = loop
        self._t0 = 0.0
        self._pos = 0

    def open(self) -> None:
        import cv2  # noqa: PLC0415

        if not Path(self.path).is_file():
            raise SourceError("FILE_MISSING", "The recording file is missing on the server")
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise SourceError("DECODE_FAILED", "The recording could not be decoded by OpenCV")
        self._finish_open(cap)
        self.native_fps = self.native_fps or 25.0
        self._t0 = time.time()
        self._pos = 0

    def read(self) -> Optional[Frame]:
        import cv2  # noqa: PLC0415

        if self.cap is None:
            return None
        # Pace to real time: skip ahead to the frame that "should" be showing now (no backlog).
        due = int((time.time() - self._t0) * self.native_fps)
        if due < self._pos:
            time.sleep((self._pos - due) / self.native_fps)
        while self._pos < due:
            if not self.cap.grab():
                break
            self._pos += 1
        frame = super().read()
        if frame is None and self.loop:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._t0, self._pos = time.time(), 0
            frame = super().read()
        self._pos += 1
        return frame


class SyntheticSource(FrameSource):
    """The deterministic simulated plaza (VCIE agents) rendered as a camera image, with ground-truth boxes."""

    kind = "synthetic"
    live = False

    def __init__(self, scenario: str = "plaza_normal", fps: float = 10.0) -> None:
        super().__init__(f"Simulation: {scenario.replace('_', ' ')}")
        self.scenario = scenario
        self.native_fps = fps
        self.engine = None

    def open(self) -> None:
        from .calibration import CameraCalibrationEngine  # noqa: PLC0415
        from .synthetic import SyntheticDemonstrationEngine  # noqa: PLC0415

        self.calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
        self.engine = SyntheticDemonstrationEngine(self.calib)
        self.engine._init_scenario(self.scenario)
        self.width, self.height = 1280, 720
        self._next = time.time()

    def default_image_points(self) -> list[tuple[float, float]]:
        return self.calib.config.source_points.to_list()

    def read(self) -> Optional[Frame]:
        if self.engine is None:
            return None
        delay = self._next - time.time()
        if delay > 0:
            time.sleep(delay)
        self._next = max(time.time(), self._next) + 1.0 / self.native_fps
        self.engine.step(dt=1.0 / self.native_fps)
        img, boxes = self.engine.generate_frame(self.width, self.height)
        self._index += 1
        return Frame(img, time.time(), self._index, synthetic_boxes=boxes)


def build_source(spec: dict[str, Any], store=None) -> FrameSource:
    kind = spec.get("kind")
    if kind == "webcam":
        return WebcamSource(int(spec.get("index", 0)), int(spec.get("width", 1280)), int(spec.get("height", 720)))
    if kind == "stream":
        return StreamSource(str(spec.get("url", "")))
    if kind == "file":
        if store is None:
            raise SourceError("NO_STORE", "Document storage is not configured")
        doc = store.get_document(str(spec.get("document_id", "")))
        if doc is None or doc["kind"] != "video":
            raise SourceError("NOT_A_VIDEO", "Choose an uploaded video recording")
        return VideoFileSource(doc["storage_path"], doc["filename"], loop=bool(spec.get("loop", True)))
    if kind == "synthetic":
        return SyntheticSource(str(spec.get("scenario", "plaza_normal")))
    raise SourceError("UNKNOWN_SOURCE", "Source kind must be webcam, stream, file or synthetic")
