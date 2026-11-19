"""Multi-object tracking so that the same person seen in many frames is counted once.

Two interchangeable trackers implement ``update(detections, t) -> list[TrackedObject]``:
  * ``ByteTrackTracker`` – Ultralytics' BYTETracker (Kalman filter + two-stage association),
                           used when the package imports cleanly.
  * ``IoUTracker``       – a dependency-light ByteTrack-style tracker (constant-velocity prediction,
                           high/low-confidence two-stage Hungarian matching on IoU). Deterministic.

``TrackHistory`` keeps time-stamped foot positions per track id. Occupancy at an instant is the
number of *confirmed* tracks currently inside a zone; "unique visitors" counts distinct ids.
Repeated detections of one person across frames therefore never inflate a count.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np

from .crowd_detection import Detection


@dataclass
class TrackedObject:
    track_id: int
    box: tuple[float, float, float, float]
    confidence: float
    confirmed: bool = True

    @property
    def foot(self) -> tuple[float, float]:
        x1, _, x2, y2 = self.box
        return ((x1 + x2) / 2.0, y2)


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def _assign(cost: np.ndarray, max_cost: float) -> list[tuple[int, int]]:
    if cost.size == 0:
        return []
    from scipy.optimize import linear_sum_assignment  # noqa: PLC0415

    rows, cols = linear_sum_assignment(cost)
    return [(int(r), int(c)) for r, c in zip(rows, cols) if cost[r, c] <= max_cost]


@dataclass
class _Track:
    track_id: int
    box: np.ndarray
    confidence: float
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(4))
    hits: int = 1
    misses: int = 0

    def predicted(self) -> np.ndarray:
        return self.box + self.velocity * (self.misses + 1)


class IoUTracker:
    name = "iou-bytetrack-style"

    def __init__(self, high_thresh: float = 0.5, low_thresh: float = 0.1, match_iou: float = 0.3,
                 min_hits: int = 2, max_misses: int = 15) -> None:
        self.high, self.low, self.match_iou = high_thresh, low_thresh, match_iou
        self.min_hits, self.max_misses = min_hits, max_misses
        self.tracks: list[_Track] = []
        self._next_id = 1

    def update(self, detections: list[Detection], t: float | None = None) -> list[TrackedObject]:
        dets = np.array([d.xyxy for d in detections], dtype=float).reshape(-1, 4)
        confs = np.array([d.confidence for d in detections], dtype=float)
        high_idx = [i for i, c in enumerate(confs) if c >= self.high]
        low_idx = [i for i, c in enumerate(confs) if self.low <= c < self.high]

        matched_tracks: set[int] = set()
        used_dets: set[int] = set()

        def match(track_ids: list[int], det_ids: list[int]) -> None:
            if not track_ids or not det_ids:
                return
            preds = np.array([self.tracks[i].predicted() for i in track_ids])
            cost = 1.0 - iou_matrix(preds, dets[det_ids])
            for r, c in _assign(cost, 1.0 - self.match_iou):
                ti, di = track_ids[r], det_ids[c]
                tr = self.tracks[ti]
                new_box = dets[di]
                tr.velocity = 0.6 * tr.velocity + 0.4 * (new_box - tr.box) / (tr.misses + 1)
                tr.box, tr.confidence = new_box, float(confs[di])
                tr.hits += 1
                tr.misses = 0
                matched_tracks.add(ti)
                used_dets.add(di)

        # Stage 1: confident detections against all tracks. Stage 2: weak detections against the rest.
        match(list(range(len(self.tracks))), high_idx)
        match([i for i in range(len(self.tracks)) if i not in matched_tracks], low_idx)

        for i, tr in enumerate(self.tracks):
            if i not in matched_tracks:
                tr.misses += 1
        self.tracks = [tr for tr in self.tracks if tr.misses <= self.max_misses]
        for di in high_idx:
            if di not in used_dets:
                self.tracks.append(_Track(self._next_id, dets[di].copy(), float(confs[di])))
                self._next_id += 1
        return [TrackedObject(tr.track_id, tuple(float(v) for v in tr.box), tr.confidence, tr.hits >= self.min_hits)
                for tr in self.tracks if tr.misses == 0]


class _Boxes:
    """Duck-typed stand-in for ultralytics Boxes (the attributes BYTETracker reads)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray) -> None:
        self.xyxy = xyxy.reshape(-1, 4).astype(np.float32)
        self.conf = conf.astype(np.float32)
        self.cls = np.zeros(len(conf), dtype=np.float32)
        w = self.xyxy[:, 2] - self.xyxy[:, 0]
        h = self.xyxy[:, 3] - self.xyxy[:, 1]
        self.xywh = np.stack([self.xyxy[:, 0] + w / 2, self.xyxy[:, 1] + h / 2, w, h], axis=1) if len(conf) else np.zeros((0, 4), np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx) -> "_Boxes":
        return _Boxes(self.xyxy[idx], self.conf[idx])


_BYTETRACK_LOCK = threading.Lock()  # BYTETracker ids come from a process-global counter


class ByteTrackTracker:
    name = "bytetrack (ultralytics)"

    def __init__(self, frame_rate: float = 10.0, track_buffer: int = 30) -> None:
        from ultralytics.trackers.byte_tracker import BYTETracker  # noqa: PLC0415

        args = SimpleNamespace(tracker_type="bytetrack", track_high_thresh=0.25, track_low_thresh=0.1,
                               new_track_thresh=0.25, track_buffer=track_buffer, match_thresh=0.8, fuse_score=True)
        import inspect  # noqa: PLC0415

        # Older releases take frame_rate; newer ones read only args (track_buffer counts frames).
        kwargs = {"frame_rate": int(max(1, round(frame_rate)))} if "frame_rate" in inspect.signature(BYTETracker.__init__).parameters else {}
        with _BYTETRACK_LOCK:
            BYTETracker.reset_id()
            self._tracker = BYTETracker(args, **kwargs)

    def update(self, detections: list[Detection], t: float | None = None) -> list[TrackedObject]:
        xyxy = np.array([d.xyxy for d in detections], dtype=np.float32).reshape(-1, 4)
        conf = np.array([d.confidence for d in detections], dtype=np.float32)
        with _BYTETRACK_LOCK:
            out = self._tracker.update(_Boxes(xyxy, conf))
        res: list[TrackedObject] = []
        arr = np.asarray(out, dtype=float)
        if arr.size == 0:
            return res
        for row in arr.reshape(-1, arr.shape[-1]):
            x1, y1, x2, y2, tid, score = (float(v) for v in row[:6])
            res.append(TrackedObject(int(tid), (x1, y1, x2, y2), score, True))
        return res


def build_tracker(preference: str = "auto", frame_rate: float = 10.0) -> tuple[Any, dict[str, Any]]:
    if preference in ("auto", "bytetrack"):
        try:
            tr = ByteTrackTracker(frame_rate=frame_rate)
            return tr, {"tracker": tr.name, "available": True}
        except Exception as exc:  # noqa: BLE001
            fallback_reason = f"ByteTrack unavailable ({type(exc).__name__}: {exc}); using IoU tracker"
            tr = IoUTracker()
            return tr, {"tracker": tr.name, "available": True, "fallback_reason": fallback_reason}
    tr = IoUTracker()
    return tr, {"tracker": tr.name, "available": True}


@dataclass
class TrackPoint:
    t: float
    x: float
    y: float
    zone: str | None


class TrackHistory:
    """Time-stamped positions per track id (in whatever coordinates the caller uses)."""

    def __init__(self) -> None:
        self.points: dict[int, list[TrackPoint]] = {}

    def add(self, track_id: int, t: float, x: float, y: float, zone: str | None) -> None:
        self.points.setdefault(track_id, []).append(TrackPoint(t, x, y, zone))

    def unique_ids(self) -> list[int]:
        return sorted(self.points)

    def unique_per_zone(self) -> dict[str, int]:
        seen: dict[str, set[int]] = {}
        for tid, pts in self.points.items():
            for p in pts:
                if p.zone:
                    seen.setdefault(p.zone, set()).add(tid)
        return {z: len(ids) for z, ids in seen.items()}

    def transitions(self) -> dict[str, int]:
        """Counts of zone-to-zone moves ("a->b"), each person counted once per crossing."""
        out: dict[str, int] = {}
        for pts in self.points.values():
            prev = None
            for p in pts:
                if p.zone is None:
                    continue
                if prev is not None and p.zone != prev:
                    key = f"{prev}->{p.zone}"
                    out[key] = out.get(key, 0) + 1
                prev = p.zone
        return out

    def fragmentation(self, min_points: int = 3) -> float:
        """Share of tracks shorter than ``min_points`` (a proxy for ID switches / flicker)."""
        if not self.points:
            return 0.0
        short = sum(1 for pts in self.points.values() if len(pts) < min_points)
        return short / len(self.points)
