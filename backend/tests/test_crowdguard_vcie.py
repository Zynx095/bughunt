"""Comprehensive Automated Test Suite for CrowdGuard Virtual Crowd Intelligence Engine (VCIE).

Tests homography calculation, coordinate projection, invalid/degenerate calibration handling,
ground-contact extraction, multi-object tracking persistence, Gaussian KDE density calculation,
movement vectors and bottleneck detection, synthetic simulation, and FastAPI REST endpoints.
"""
from __future__ import annotations

import math
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.crowdguard.calibration import CameraCalibrationEngine, is_convex_quad, order_points_clockwise
from app.crowdguard.density import VirtualCrowdDensityEngine
from app.crowdguard.detection import PersonDetectionEngine
from app.crowdguard.movement import MovementIntelligenceEngine
from app.crowdguard.perspective import BirdEyeViewGenerator
from app.crowdguard.pipeline import VirtualCrowdIntelligencePipeline
from app.crowdguard.schemas import (
    BoundingBox,
    CalibrationConfig,
    CalibrationPoint,
    CalibrationQuad,
    HeatmapMode,
    TrackedPerson,
    ZoneDefinition,
)
from app.crowdguard.synthetic import SyntheticDemonstrationEngine
from app.crowdguard.venue import VenueDigitalTwin
from app.main import app


# ---------------------------------------------------------
# 1. Calibration and Homography Tests
# ---------------------------------------------------------

def test_homography_calculation_and_projection():
    """Tests 4-point homography estimation and forward/inverse coordinate mapping."""
    quad = CalibrationQuad(
        top_left=CalibrationPoint(x=100.0, y=100.0),
        top_right=CalibrationPoint(x=500.0, y=100.0),
        bottom_right=CalibrationPoint(x=600.0, y=400.0),
        bottom_left=CalibrationPoint(x=50.0, y=400.0),
    )
    cfg = CalibrationConfig(
        source_points=quad,
        target_width_px=800,
        target_height_px=600,
        ground_width_meters=20.0,
        ground_height_meters=15.0,
    )
    engine = CameraCalibrationEngine(cfg)

    assert engine.is_valid
    assert engine.H is not None
    assert engine.H_inv is not None
    assert engine.result.meters_per_pixel_x == pytest.approx(20.0 / 800.0)
    assert engine.result.meters_per_pixel_y == pytest.approx(15.0 / 600.0)

    # Test projection of Top-Left corner: should map to (0, 0)
    u_tl, v_tl = engine.project_camera_to_birdseye((100.0, 100.0))
    assert u_tl == pytest.approx(0.0, abs=1e-2)
    assert v_tl == pytest.approx(0.0, abs=1e-2)

    # Test projection of Bottom-Right corner: should map to (800, 600)
    u_br, v_br = engine.project_camera_to_birdseye((600.0, 400.0))
    assert u_br == pytest.approx(800.0, abs=1e-2)
    assert v_br == pytest.approx(600.0, abs=1e-2)

    # Test inverse projection: (800, 600) in bird's-eye should map back to (600, 400)
    cam_x, cam_y = engine.project_birdseye_to_camera((800.0, 600.0))
    assert cam_x == pytest.approx(600.0, abs=1e-2)
    assert cam_y == pytest.approx(400.0, abs=1e-2)

    # Test real-world metric conversion
    world_m = engine.to_world_meters((400.0, 300.0))
    assert world_m is not None
    assert world_m[0] == pytest.approx(10.0, abs=1e-2)
    assert world_m[1] == pytest.approx(7.5, abs=1e-2)


def test_degenerate_and_collinear_calibration_handling():
    """Verifies that collinear or non-convex points are safely rejected without crashing."""
    # Collinear points (all lie on a horizontal line y=200)
    collinear_quad = CalibrationQuad(
        top_left=CalibrationPoint(x=100.0, y=200.0),
        top_right=CalibrationPoint(x=200.0, y=200.0),
        bottom_right=CalibrationPoint(x=300.0, y=200.0),
        bottom_left=CalibrationPoint(x=400.0, y=200.0),
    )
    cfg = CalibrationConfig(source_points=collinear_quad)
    engine = CameraCalibrationEngine(cfg)

    assert not engine.is_valid
    assert engine.H is None
    assert engine.result is not None
    assert "Degenerate calibration" in engine.result.message


def test_order_points_clockwise():
    """Tests automatic ordering heuristic for disordered points."""
    pts = np.array([
        [500.0, 400.0],  # BR
        [100.0, 100.0],  # TL
        [50.0, 400.0],   # BL
        [400.0, 100.0],  # TR
    ], dtype=np.float32)

    ordered = order_points_clockwise(pts)
    # Ordered must be TL, TR, BR, BL
    assert ordered[0][0] == pytest.approx(100.0)
    assert ordered[0][1] == pytest.approx(100.0)
    assert ordered[1][0] == pytest.approx(400.0)
    assert ordered[2][0] == pytest.approx(500.0)
    assert ordered[3][0] == pytest.approx(50.0)


# ---------------------------------------------------------
# 2. Ground Contact Extraction & Detection Tests
# ---------------------------------------------------------

def test_ground_contact_point_extraction():
    """Verifies that foot/ground-contact point is bottom-center of bounding box."""
    bbox = BoundingBox(x1=100.0, y1=50.0, x2=160.0, y2=210.0, confidence=0.88)
    foot_x, foot_y = bbox.ground_contact_point
    assert foot_x == pytest.approx((100.0 + 160.0) / 2.0)
    assert foot_y == pytest.approx(210.0)


def test_detection_fallback_and_projection():
    """Tests detection engine fallback when weights are offline."""
    calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
    detector = PersonDetectionEngine(calib, use_fallback_if_missing=True)

    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Draw a synthetic pedestrian rectangle in frame
    cv2.rectangle(dummy_frame, (300, 250), (360, 450), (200, 200, 200), -1)

    boxes = detector.detect(dummy_frame, confidence_threshold=0.2)
    assert isinstance(boxes, list)

    projected = detector.extract_ground_contact_and_project(boxes)
    assert isinstance(projected, list)
    for box, cam_pt, be_pt in projected:
        assert len(cam_pt) == 2
        assert len(be_pt) == 2


# ---------------------------------------------------------
# 3. Multi-Object Tracking & Persistence Tests
# ---------------------------------------------------------

def test_multi_object_tracker_persistence():
    """Verifies that an individual tracked across sequential frames retains persistent ID."""
    calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
    pipeline = VirtualCrowdIntelligencePipeline(calib.config)

    # Initial frame
    res1 = pipeline.step_synthetic(scenario="plaza_normal", dt=0.1)
    assert res1.active_tracks_count > 0
    initial_ids = {t.track_id for t in res1.tracks}

    # Step sequential frames
    res2 = pipeline.step_synthetic(scenario="plaza_normal", dt=0.1)
    res3 = pipeline.step_synthetic(scenario="plaza_normal", dt=0.1)

    next_ids = {t.track_id for t in res3.tracks}
    # Large majority of track IDs must persist across sequential frames
    common_ids = initial_ids.intersection(next_ids)
    assert len(common_ids) >= len(initial_ids) * 0.75, "Track IDs must persist across frames without re-counting individuals"


# ---------------------------------------------------------
# 4. Crowd Density & Gaussian KDE Tests
# ---------------------------------------------------------

def test_gaussian_kde_density_calculation():
    """Verifies Gaussian KDE density grid calculation and physical scaling."""
    calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
    density_engine = VirtualCrowdDensityEngine(calib, bandwidth_sigma=25.0)

    # Create 5 clustered synthetic tracks in central plaza (u=400, v=300)
    tracks = []
    for i in range(5):
        box = BoundingBox(x1=100.0, y1=100.0, x2=150.0, y2=250.0, confidence=0.9)
        tracks.append(
            TrackedPerson(
                track_id=i + 1,
                camera_bbox=box,
                camera_ground_point=(125.0, 250.0),
                birdseye_point=(400.0 + i * 2.0, 300.0 + i * 2.0),
                speed_mps=0.8,
            )
        )

    grid = density_engine.compute_density_grid(tracks, grid_width=800, grid_height=600)
    assert grid.shape == (600, 800)
    peak_val = float(np.max(grid))
    assert peak_val > 0.0, "Cluster must produce positive continuous density"

    # Peak must be concentrated near cluster center (x=400, y=300)
    py, px = np.unravel_index(np.argmax(grid), grid.shape)
    assert abs(px - 400) <= 5
    assert abs(py - 300) <= 5

    # Density far from cluster (e.g. corner x=50, y=50) should be near zero
    assert grid[50, 50] == pytest.approx(0.0, abs=1e-3)


def test_heatmap_render_modes():
    """Tests rendering all 4 heatmap modes: Gaussian, Point, Zone, and Movement."""
    calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
    density_engine = VirtualCrowdDensityEngine(calib)
    venue = VenueDigitalTwin()

    base_img = np.zeros((600, 800, 3), dtype=np.uint8)
    box = BoundingBox(x1=100, y1=100, x2=150, y2=200, confidence=0.9)
    tracks = [
        TrackedPerson(
            track_id=1,
            camera_bbox=box,
            camera_ground_point=(125.0, 200.0),
            birdseye_point=(400.0, 300.0),
            speed_mps=0.2,
        )
    ]

    for mode in [HeatmapMode.GAUSSIAN, HeatmapMode.POINT, HeatmapMode.ZONE, HeatmapMode.MOVEMENT]:
        out = density_engine.render_heatmap(
            base_image=base_img,
            tracks=tracks,
            zones=venue.model.zones,
            mode=mode,
        )
        assert out.shape == (600, 800, 3)
        assert out.dtype == np.uint8


# ---------------------------------------------------------
# 5. Movement Vectors & Congestion Alerts
# ---------------------------------------------------------

def test_movement_vector_and_bottleneck_detection():
    """Tests velocity vector extraction and bottleneck identification."""
    calib = CameraCalibrationEngine(CameraCalibrationEngine.get_default_calibration())
    mov_engine = MovementIntelligenceEngine(calib, bottleneck_speed_mps_threshold=0.45)

    # Build tracks with position history
    t1 = TrackedPerson(
        track_id=10,
        camera_bbox=BoundingBox(x1=100, y1=100, x2=140, y2=200, confidence=0.9),
        camera_ground_point=(120.0, 200.0),
        birdseye_point=(300.0, 300.0),
        speed_mps=0.20,  # Below bottleneck threshold
    )
    t1.history = [
        t1.history[0] if t1.history else None,
    ]
    from app.crowdguard.schemas import TrackPoint
    t1.history = [
        TrackPoint(frame_idx=1, timestamp_s=0.0, camera_x=120, camera_y=200, birdseye_x=299.0, birdseye_y=300.0, speed_mps=0.2),
        TrackPoint(frame_idx=2, timestamp_s=0.1, camera_x=120, camera_y=200, birdseye_x=300.0, birdseye_y=300.0, speed_mps=0.2),
    ]

    vectors = mov_engine.extract_movement_vectors([t1])
    assert len(vectors) == 1
    assert vectors[0].risk_indicator == "stagnant"

    # Dense grid around t1
    density_grid = np.zeros((600, 800), dtype=np.float32)
    density_grid[300, 300] = 2.4  # High density

    alerts = mov_engine.analyze_congestion_and_alerts([t1], [], density_grid, timestamp_s=1.0)
    assert len(alerts) >= 1
    assert alerts[0].alert_type == "bottleneck"


# ---------------------------------------------------------
# 6. FastAPI REST Endpoints Tests
# ---------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def test_api_crowdguard_presets(client):
    """Tests GET /api/crowdguard/presets."""
    response = client.get("/api/crowdguard/presets")
    assert response.status_code == 200
    data = response.json()
    assert "calibration" in data
    assert "venue" in data
    assert "scenarios" in data
    assert len(data["scenarios"]) >= 4


def test_api_crowdguard_calibration_endpoint(client):
    """Tests POST /api/crowdguard/calibration."""
    payload = {
        "source_points": {
            "top_left": {"x": 430.0, "y": 280.0},
            "top_right": {"x": 850.0, "y": 280.0},
            "bottom_right": {"x": 1150.0, "y": 680.0},
            "bottom_left": {"x": 130.0, "y": 680.0},
        },
        "target_width_px": 800,
        "target_height_px": 600,
        "ground_width_meters": 24.0,
        "ground_height_meters": 18.0,
    }
    response = client.post("/api/crowdguard/calibration", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["target_width_px"] == 800
    assert data["homography_matrix"] is not None


def test_api_crowdguard_simulation_step_and_images(client):
    """Tests stepping simulation and retrieving image streams."""
    step_resp = client.post("/api/crowdguard/simulation/step?scenario=bottleneck&mode=gaussian")
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["is_synthetic"] is True
    assert step_data["active_tracks_count"] > 0

    # Test camera frame endpoint
    cam_resp = client.get("/api/crowdguard/analysis/live/frame")
    assert cam_resp.status_code == 200
    assert cam_resp.headers["content-type"] == "image/jpeg"
    assert len(cam_resp.content) > 1000

    # Test bird's-eye frame endpoint
    be_resp = client.get("/api/crowdguard/analysis/live/birdseye")
    assert be_resp.status_code == 200
    assert be_resp.headers["content-type"] == "image/jpeg"

    # Test heatmap image endpoint
    heat_resp = client.get("/api/crowdguard/analysis/live/heatmap")
    assert heat_resp.status_code == 200
    assert heat_resp.headers["content-type"] == "image/jpeg"

    # Test tracks telemetry endpoint
    tracks_resp = client.get("/api/crowdguard/analysis/live/tracks")
    assert tracks_resp.status_code == 200
    t_data = tracks_resp.json()
    assert "tracks" in t_data
    assert "movement_vectors" in t_data
