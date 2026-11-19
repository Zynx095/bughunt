"""Deterministic Synthetic Crowd Simulation Engine for CrowdGuard VCIE.

Generates reproducible, physics-grounded crowd movement scenarios with projective
camera rendering and top-down ground-truth coordinates.
Guarantees a fully functional demonstration environment without requiring external model downloads.
All synthetic outputs are explicitly labelled.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

from .calibration import CameraCalibrationEngine
from .schemas import (
    BoundingBox,
    CalibrationConfig,
    CalibrationPoint,
    CalibrationQuad,
    TrackedPerson,
    ZoneDefinition,
)


class SyntheticAgent:
    """An autonomous synthetic pedestrian with goals, velocity, and avoidance."""

    def __init__(
        self,
        agent_id: int,
        start_x: float,
        start_y: float,
        target_x: float,
        target_y: float,
        speed_base: float = 1.2,
        color_seed: int = 42,
    ):
        self.id = agent_id
        self.x = start_x
        self.y = start_y
        self.target_x = target_x
        self.target_y = target_y
        self.speed_base = speed_base
        self.current_speed = speed_base
        self.vx = 0.0
        self.vy = 0.0
        self.radius_px = 12.0
        # Color seed for visual variety in camera view
        rng = random.Random(color_seed + agent_id)
        self.clothing_color = (rng.randint(60, 220), rng.randint(60, 220), rng.randint(60, 220))

    def step(self, neighbors: List[SyntheticAgent], dt: float = 0.1, constrict_x: Optional[Tuple[float, float]] = None):
        """Advances agent state using social force model heuristics."""
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.hypot(dx, dy)

        if dist < 8.0:
            # Reached target; select return or wander target
            self.target_x, self.target_y = self._pick_new_target(self.x, self.y)
            dx = self.target_x - self.x
            dy = self.target_y - self.y
            dist = math.hypot(dx, dy)

        # Desired unit direction
        if dist > 1e-4:
            des_vx = (dx / dist) * self.speed_base
            des_vy = (dy / dist) * self.speed_base
        else:
            des_vx, des_vy = 0.0, 0.0

        # Social repulsion from nearby neighbors
        rep_vx, rep_vy = 0.0, 0.0
        local_crowding = 0
        for other in neighbors:
            if other.id == self.id:
                continue
            ox = self.x - other.x
            oy = self.y - other.y
            odist = math.hypot(ox, oy)
            if 0 < odist < (self.radius_px * 2.8):
                local_crowding += 1
                strength = (self.radius_px * 2.8 - odist) / (self.radius_px * 2.8)
                rep_vx += (ox / odist) * strength * 1.5
                rep_vy += (oy / odist) * strength * 1.5

        # Speed reduction when overcrowded (bottleneck dynamics)
        slowdown = max(0.2, 1.0 - (local_crowding * 0.18))
        self.current_speed = self.speed_base * slowdown

        # Apply constrictions if within a bottleneck corridor
        if constrict_x and constrict_x[0] <= self.x <= constrict_x[1]:
            self.current_speed *= 0.55

        # Integrate velocity
        self.vx = (des_vx + rep_vx) * slowdown
        self.vy = (des_vy + rep_vy) * slowdown

        # Pixels per second to pixel displacement
        px_scale = 28.0  # ~28 px per meter
        self.x += self.vx * px_scale * dt
        self.y += self.vy * px_scale * dt

    def _pick_new_target(self, cur_x: float, cur_y: float) -> Tuple[float, float]:
        # Return to opposite corridor or plaza
        return (random.uniform(80.0, 720.0), random.uniform(80.0, 520.0))


class SyntheticDemonstrationEngine:
    """Generates synthetic multi-agent crowd scenarios and renders camera footage."""

    def __init__(self, calibration: CameraCalibrationEngine):
        self.calib = calibration
        self.agents: List[SyntheticAgent] = []
        self.scenario_name = "plaza_normal"
        self.current_frame = 0
        self._init_scenario("plaza_normal")

    def _init_scenario(self, scenario: str):
        self.scenario_name = scenario
        self.agents.clear()
        rng = random.Random(1337)  # Deterministic seed

        w = self.calib.config.target_width_px
        h = self.calib.config.target_height_px

        if scenario == "bottleneck":
            # 45 agents funneling from Plaza into Narrow Corridor
            for i in range(45):
                start_x = rng.uniform(80.0, 360.0)
                start_y = rng.uniform(80.0, 300.0)
                # Funnel into narrow exit corridor (x=500..600, y=480..540)
                target_x = rng.uniform(480.0, 540.0)
                target_y = rng.uniform(460.0, 520.0)
                self.agents.append(SyntheticAgent(i + 1, start_x, start_y, target_x, target_y, speed_base=rng.uniform(1.0, 1.4)))

        elif scenario == "counterflow":
            # Two opposing streams (Group A moving Right->Left, Group B moving Left->Right)
            for i in range(20):
                # Stream 1: Left to Right
                self.agents.append(SyntheticAgent(i + 1, rng.uniform(80.0, 180.0), rng.uniform(220.0, 320.0),
                                                  rng.uniform(620.0, 720.0), rng.uniform(220.0, 320.0), speed_base=1.3))
            for i in range(20, 40):
                # Stream 2: Right to Left
                self.agents.append(SyntheticAgent(i + 1, rng.uniform(620.0, 720.0), rng.uniform(240.0, 340.0),
                                                  rng.uniform(80.0, 180.0), rng.uniform(240.0, 340.0), speed_base=1.3))

        elif scenario == "surge_gate":
            # Rapid surge of 60 agents converging onto North Ingress Gate
            for i in range(60):
                start_x = rng.uniform(100.0, 700.0)
                start_y = rng.uniform(250.0, 550.0)
                target_x = rng.uniform(180.0, 260.0)
                target_y = rng.uniform(60.0, 110.0)
                self.agents.append(SyntheticAgent(i + 1, start_x, start_y, target_x, target_y, speed_base=rng.uniform(1.2, 1.6)))

        else:
            # Default Plaza Gathering: 35 agents moving between portals and zones
            for i in range(35):
                start_x = rng.uniform(80.0, float(w - 80))
                start_y = rng.uniform(80.0, float(h - 80))
                target_x = rng.uniform(100.0, float(w - 100))
                target_y = rng.uniform(100.0, float(h - 100))
                self.agents.append(SyntheticAgent(i + 1, start_x, start_y, target_x, target_y, speed_base=rng.uniform(0.9, 1.4)))

    def step(self, dt: float = 0.1):
        """Advances simulation by dt seconds."""
        constriction = (420.0, 560.0) if self.scenario_name == "bottleneck" else None
        for agent in self.agents:
            agent.step(self.agents, dt=dt, constrict_x=constriction)
        self.current_frame += 1

    def generate_frame(
        self,
        camera_width: int = 1280,
        camera_height: int = 720,
    ) -> Tuple[np.ndarray, List[BoundingBox]]:
        """Renders camera perspective video frame using inverse homography projection.
        
        Renders floor perspective, ground grid, pedestrian silhouettes, and shadows.
        
        Returns:
            Tuple of (camera_frame_bgr, ground_truth_bounding_boxes)
        """
        frame = np.zeros((camera_height, camera_width, 3), dtype=np.uint8)
        # Background: venue hall ambiance
        frame[:] = (22, 24, 30)

        # Draw hall perspective floor
        quad_pts = np.array(self.calib.config.source_points.to_list(), dtype=np.int32)
        cv2.fillPoly(frame, [quad_pts], (34, 38, 48))
        cv2.polylines(frame, [quad_pts], isClosed=True, color=(55, 65, 80), thickness=2, lineType=cv2.LINE_AA)

        # Draw perspective floor tiles/lines
        for alpha in [0.25, 0.5, 0.75]:
            p1 = (1.0 - alpha) * quad_pts[0] + alpha * quad_pts[3]
            p2 = (1.0 - alpha) * quad_pts[1] + alpha * quad_pts[2]
            cv2.line(frame, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (42, 48, 60), 1, cv2.LINE_AA)

        boxes: List[BoundingBox] = []

        # Sort agents by bird's-eye y coordinate (back to front rendering order for correct occlusion!)
        sorted_agents = sorted(self.agents, key=lambda a: a.y)

        for agent in sorted_agents:
            be_pt = (agent.x, agent.y)
            try:
                # Project ground point from bird's-eye canvas to camera image plane
                cam_x, cam_y = self.calib.project_birdseye_to_camera(be_pt)
            except Exception:
                continue

            if not (0 <= cam_x < camera_width and 0 <= cam_y < camera_height):
                continue

            # Scale pedestrian size based on perspective depth (agents closer to bottom are larger!)
            # y=280 (far) -> scale=0.45; y=680 (near) -> scale=1.1
            depth_ratio = max(0.2, min(1.2, (cam_y - 200.0) / 480.0))
            box_h = int(round(110.0 * depth_ratio))
            box_w = int(round(38.0 * depth_ratio))

            x1 = cam_x - (box_w / 2.0)
            y1 = cam_y - box_h
            x2 = cam_x + (box_w / 2.0)
            y2 = cam_y

            ix1, iy1, ix2, iy2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))

            # 1. Ground contact shadow (ellipse)
            shadow_axes = (int(round(box_w * 0.7)), int(round(box_w * 0.28)))
            cv2.ellipse(frame, (int(round(cam_x)), int(round(cam_y))), shadow_axes, 0, 0, 360, (15, 17, 22), -1, cv2.LINE_AA)

            # 2. Render stylized person silhouette
            # Torso/legs
            cv2.rectangle(frame, (ix1 + 2, iy1 + int(box_h * 0.28)), (ix2 - 2, iy2), agent.clothing_color, -1)
            # Head
            head_r = max(3, int(round(box_w * 0.32)))
            head_center = (int(round(cam_x)), iy1 + head_r + 2)
            cv2.circle(frame, head_center, head_r, (230, 200, 180), -1, cv2.LINE_AA)

            boxes.append(
                BoundingBox(
                    x1=float(ix1),
                    y1=float(iy1),
                    x2=float(ix2),
                    y2=float(iy2),
                    confidence=0.92,
                    class_name="person",
                )
            )

        # Overlay synthetic mode indicator watermark
        cv2.putText(
            frame,
            f"SYNTHETIC SIMULATION [{self.scenario_name.upper()}] · FRAME {self.current_frame}",
            (20, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 215, 255),
            1,
            cv2.LINE_AA,
        )

        return frame, boxes

    def export_sample_video(
        self,
        output_path: str,
        num_frames: int = 150,
        fps: int = 25,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        """Generates an MP4 sample video on disk for offline demonstration and testing."""
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if not writer.isOpened():
            raise IOError(f"Could not open VideoWriter at {output_path}")

        try:
            for _ in range(num_frames):
                self.step(dt=1.0 / fps)
                frame, _ = self.generate_frame(width, height)
                writer.write(frame)
        finally:
            writer.release()

        return output_path
