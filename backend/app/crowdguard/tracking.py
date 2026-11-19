"""Multi-Object Tracking Engine for CrowdGuard VCIE.

Implements persistent identity tracking across sequential frames using a 2D Kalman filter
and ground-plane spatial association (ByteTrack / SORT paradigm).
Estimates velocity vectors, directional headings, speeds in m/s, and maintains track histories.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import numpy as np

from .calibration import CameraCalibrationEngine
from .schemas import BoundingBox, TrackedPerson, TrackPoint


class KalmanTracker2D:
    """Kalman filter for tracking 2D ground position (u, v) and velocity (vx, vy).
    
    State vector: x = [u, v, vx, vy]^T
    Measurement vector: z = [u, v]^T
    """

    def __init__(self, initial_u: float, initial_v: float, dt: float = 1.0 / 30.0):
        self.dt = dt
        # State vector [u, v, vx, vy]
        self.x = np.array([initial_u, initial_v, 0.0, 0.0], dtype=np.float64)

        # State transition matrix F
        self.F = np.array([
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

        # Measurement matrix H
        self.H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ], dtype=np.float64)

        # State covariance P
        self.P = np.eye(4, dtype=np.float64) * 20.0
        self.P[2, 2] *= 100.0  # high uncertainty for initial velocity
        self.P[3, 3] *= 100.0

        # Process noise Q
        q_pos = 0.5
        q_vel = 1.5
        self.Q = np.diag([q_pos, q_pos, q_vel, q_vel]).astype(np.float64)

        # Measurement noise R
        self.R = np.eye(2, dtype=np.float64) * 5.0

    def predict(self, dt: Optional[float] = None) -> Tuple[float, float]:
        """Predicts the next state."""
        if dt is not None and abs(dt - self.dt) > 1e-4:
            self.dt = dt
            self.F[0, 2] = dt
            self.F[1, 3] = dt

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return (float(self.x[0]), float(self.x[1]))

    def update(self, measured_u: float, measured_v: float):
        """Updates the state with a new measurement."""
        z = np.array([measured_u, measured_v], dtype=np.float64)
        y = z - (self.H @ self.x)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)

        self.x = self.x + (K @ y)
        I = np.eye(4, dtype=np.float64)
        self.P = (I - K @ self.H) @ self.P

    @property
    def position(self) -> Tuple[float, float]:
        return (float(self.x[0]), float(self.x[1]))

    @property
    def velocity(self) -> Tuple[float, float]:
        return (float(self.x[2]), float(self.x[3]))


class TrackInternal:
    """Internal representation of an active person track."""

    def __init__(
        self,
        track_id: int,
        camera_bbox: BoundingBox,
        camera_ground_pt: Tuple[float, float],
        birdseye_pt: Tuple[float, float],
        frame_idx: int,
        timestamp_s: float,
    ):
        self.track_id = track_id
        self.camera_bbox = camera_bbox
        self.camera_ground_pt = camera_ground_pt
        self.birdseye_pt = birdseye_pt
        self.kf = KalmanTracker2D(birdseye_pt[0], birdseye_pt[1])

        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.confidence = camera_bbox.confidence
        self.history: List[TrackPoint] = [
            TrackPoint(
                frame_idx=frame_idx,
                timestamp_s=timestamp_s,
                camera_x=camera_ground_pt[0],
                camera_y=camera_ground_pt[1],
                birdseye_x=birdseye_pt[0],
                birdseye_y=birdseye_pt[1],
                speed_mps=0.0,
            )
        ]


class MultiObjectTracker:
    """Multi-object tracker with persistence, Kalman smoothing, and velocity estimation."""

    def __init__(
        self,
        calibration: CameraCalibrationEngine,
        max_age_frames: int = 25,
        min_hits: int = 2,
        distance_threshold_px: float = 65.0,
        duplicate_distance_threshold_px: float = 18.0,
        max_history_length: int = 45,
    ):
        self.calib = calibration
        self.max_age_frames = max_age_frames
        self.min_hits = min_hits
        self.distance_threshold_px = distance_threshold_px
        self.duplicate_distance_threshold_px = duplicate_distance_threshold_px
        self.max_history_length = max_history_length

        self.tracks: Dict[int, TrackInternal] = {}
        self._next_id = 1
        self._last_timestamp_s = 0.0

    def update(
        self,
        detections: List[Tuple[BoundingBox, Tuple[float, float], Tuple[float, float]]],
        frame_idx: int,
        timestamp_s: float,
        external_ids: Optional[List[int]] = None,
    ) -> List[TrackedPerson]:
        """Updates tracks with new detections from current frame.

        Args:
            detections: List of (BoundingBox, camera_ground_pt, birdseye_pt)
            frame_idx: Current frame index
            timestamp_s: Video timestamp in seconds
            external_ids: Optional identity per detection from an image-space tracker (ByteTrack). When
                given, identity comes from that tracker and this class only adds ground-plane kinematics
                (Kalman-smoothed position, velocity, speed in m/s). Otherwise detections are associated by
                ground-plane distance.

        Returns:
            List of confirmed TrackedPerson objects.
        """
        dt = max(0.01, timestamp_s - self._last_timestamp_s) if self._last_timestamp_s > 0 else (1.0 / 30.0)
        self._last_timestamp_s = timestamp_s

        # 1. Deduplicate raw detections in bird's-eye space (avoid duplicate boxes on same person)
        if external_ids is not None and len(external_ids) != len(detections):
            raise ValueError("external_ids must match detections one-to-one")
        unique_detections = detections if external_ids is not None else self._deduplicate_detections(detections)

        # 2. Kalman predict for all existing tracks
        for trk in self.tracks.values():
            trk.kf.predict(dt=dt)
            trk.age += 1
            trk.time_since_update += 1

        # 3. Associate detections to existing tracks using Euclidean distance in bird's-eye canvas
        track_ids = list(self.tracks.keys())
        assigned_det_indices = set()
        assigned_track_ids = set()

        if external_ids is not None:
            for j, (tid, det) in enumerate(zip(external_ids, unique_detections)):
                box, cam_pt, be_pt = det
                if tid in self.tracks:
                    self._apply_match(self.tracks[tid], box, cam_pt, be_pt, frame_idx, timestamp_s)
                else:
                    self.tracks[tid] = TrackInternal(tid, box, cam_pt, be_pt, frame_idx, timestamp_s)
                    self._next_id = max(self._next_id, tid + 1)
                assigned_det_indices.add(j)
            track_ids = []  # skip distance association

        if track_ids and unique_detections:
            # Build cost matrix
            cost_matrix = np.zeros((len(track_ids), len(unique_detections)), dtype=np.float64)
            for i, tid in enumerate(track_ids):
                pred_pos = self.tracks[tid].kf.position
                for j, (_, _, be_pt) in enumerate(unique_detections):
                    dist = math.hypot(pred_pos[0] - be_pt[0], pred_pos[1] - be_pt[1])
                    cost_matrix[i, j] = dist

            # Greedy minimum-cost matching (or Hungarian)
            while True:
                min_val = np.min(cost_matrix)
                if min_val > self.distance_threshold_px or np.isinf(min_val):
                    break
                row, col = np.unravel_index(np.argmin(cost_matrix), cost_matrix.shape)
                tid = track_ids[row]
                if tid not in assigned_track_ids and col not in assigned_det_indices:
                    assigned_track_ids.add(tid)
                    assigned_det_indices.add(col)

                    # Update track state with matched detection
                    box, cam_pt, be_pt = unique_detections[col]
                    self._apply_match(self.tracks[tid], box, cam_pt, be_pt, frame_idx, timestamp_s)

                # Mask out this row and column
                cost_matrix[row, :] = np.inf
                cost_matrix[:, col] = np.inf

        # 4. Initialize new tracks for unmatched detections
        for j, (box, cam_pt, be_pt) in enumerate(unique_detections):
            if j not in assigned_det_indices:
                new_id = self._next_id
                self._next_id += 1
                self.tracks[new_id] = TrackInternal(
                    track_id=new_id,
                    camera_bbox=box,
                    camera_ground_pt=cam_pt,
                    birdseye_pt=be_pt,
                    frame_idx=frame_idx,
                    timestamp_s=timestamp_s,
                )

        # 5. Remove expired tracks
        dead_ids = [tid for tid, trk in self.tracks.items() if trk.time_since_update > self.max_age_frames]
        for tid in dead_ids:
            del self.tracks[tid]

        # 6. Format active confirmed tracks
        active_list: List[TrackedPerson] = []
        for tid, trk in self.tracks.items():
            # Must meet minimum hits or be newly created with good confidence
            if trk.hits >= self.min_hits or trk.confidence >= 0.5:
                vel_px = trk.kf.velocity
                heading_rad = math.atan2(vel_px[1], vel_px[0])
                heading_deg = (math.degrees(heading_rad) + 360.0) % 360.0

                speed_mps = self._calculate_speed_mps(trk)
                world_pos = self.calib.to_world_meters(trk.birdseye_pt)

                # Velocity in m/s
                vel_mps = None
                res = self.calib.result
                if res and res.meters_per_pixel_x and res.meters_per_pixel_y:
                    vel_mps = (vel_px[0] * res.meters_per_pixel_x, vel_px[1] * res.meters_per_pixel_y)

                active_list.append(
                    TrackedPerson(
                        track_id=tid,
                        camera_bbox=trk.camera_bbox,
                        camera_ground_point=trk.camera_ground_pt,
                        birdseye_point=trk.birdseye_pt,
                        world_pos_meters=world_pos,
                        velocity_vector_px=(round(vel_px[0], 2), round(vel_px[1], 2)),
                        velocity_vector_mps=(round(vel_mps[0], 2), round(vel_mps[1], 2)) if vel_mps else None,
                        speed_mps=round(speed_mps, 2),
                        heading_deg=round(heading_deg, 1),
                        confidence=round(trk.confidence, 3),
                        age_frames=trk.age,
                        history=trk.history.copy(),
                    )
                )

        return active_list

    def _apply_match(self, trk: TrackInternal, box: BoundingBox, cam_pt: Tuple[float, float],
                     be_pt: Tuple[float, float], frame_idx: int, timestamp_s: float) -> None:
        trk.kf.update(be_pt[0], be_pt[1])
        trk.camera_bbox = box
        trk.camera_ground_pt = cam_pt
        trk.birdseye_pt = be_pt
        trk.confidence = box.confidence
        trk.hits += 1
        trk.time_since_update = 0
        trk.history.append(TrackPoint(frame_idx=frame_idx, timestamp_s=timestamp_s, camera_x=cam_pt[0], camera_y=cam_pt[1],
                                      birdseye_x=be_pt[0], birdseye_y=be_pt[1], speed_mps=0.0))
        trk.history[-1].speed_mps = self._calculate_speed_mps(trk)
        if len(trk.history) > self.max_history_length:  # bounded history (memory)
            trk.history.pop(0)

    def _deduplicate_detections(
        self,
        detections: List[Tuple[BoundingBox, Tuple[float, float], Tuple[float, float]]],
    ) -> List[Tuple[BoundingBox, Tuple[float, float], Tuple[float, float]]]:
        """Suppresses duplicate detections within close ground-plane distance."""
        if len(detections) <= 1:
            return detections

        # Sort by confidence descending
        sorted_dets = sorted(detections, key=lambda d: d[0].confidence, reverse=True)
        kept = []
        for det in sorted_dets:
            _, _, be_pt = det
            duplicate = False
            for k in kept:
                _, _, k_be = k
                if math.hypot(be_pt[0] - k_be[0], be_pt[1] - k_be[1]) < self.duplicate_distance_threshold_px:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(det)
        return kept

    def _calculate_speed_mps(self, trk: TrackInternal) -> float:
        """Estimates speed in physical meters per second using track history."""
        res = self.calib.result
        if len(trk.history) < 2 or not res or not res.meters_per_pixel_x or not res.meters_per_pixel_y:
            # Fallback estimate from velocity in pixels assuming 30 fps
            vel_mag = math.hypot(trk.kf.velocity[0], trk.kf.velocity[1])
            m_px = (res.meters_per_pixel_x or 0.03) if res else 0.03
            return vel_mag * m_px

        # Compute smoothed speed over last 3 points
        pts = trk.history[-min(4, len(trk.history)):]
        p_first = pts[0]
        p_last = pts[-1]
        dt = max(0.01, p_last.timestamp_s - p_first.timestamp_s)

        dx_m = (p_last.birdseye_x - p_first.birdseye_x) * res.meters_per_pixel_x
        dy_m = (p_last.birdseye_y - p_first.birdseye_y) * res.meters_per_pixel_y
        dist_m = math.hypot(dx_m, dy_m)
        speed = dist_m / dt
        return min(12.0, max(0.0, speed))  # clamp to realistic pedestrian speed
