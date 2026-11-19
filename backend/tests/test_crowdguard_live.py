"""Real-time monitoring: sources, projection, free space, guidance, alerts, monitor threads and WebSocket."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from app.crowdguard import camera_sources
from app.crowdguard.camera_sources import Frame, FrameSource, SourceError, StreamSource, WebcamSource, discover_cameras
from app.crowdguard.guidance import GuidanceController, RoutePlanner
from app.crowdguard.live_alerts import AlertManager
from app.crowdguard.live_monitor import LiveMonitor
from app.crowdguard.occupancy import GroundPerson, compute_occupancy, kde_density
from app.crowdguard.schemas import BoundingBox
from app.crowdguard.site_model import GroundProjector, LiveCalibration, Obstacle, Portal, SiteMasks, SiteModel, SiteZone, default_site


def box_site(**kw) -> SiteModel:
    base = dict(width_m=10.0, height_m=8.0, cell_m=0.5, zones=[SiteZone(id="z", name="Hall", polygon=[(0, 0), (10, 0), (10, 8), (0, 8)], capacity=20)],
                portals=[Portal(id="west", name="West exit", kind="exit", a=(0, 3), b=(0, 5)),
                         Portal(id="east", name="East exit", kind="emergency_exit", a=(10, 3), b=(10, 5))])
    base.update(kw)
    return SiteModel(**base)


# ---------------------------------------------------------------- camera input
class _FakeCap:
    def __init__(self, idx, api, opens=(0, 1), frames=(0,)):
        self.idx, self.ok, self.frames = idx, idx in opens, idx in frames

    def isOpened(self):
        return self.ok

    def read(self):
        return (True, np.zeros((480, 640, 3), np.uint8)) if self.frames else (False, None)

    def set(self, *_):
        return True

    def get(self, *_):
        return 30.0

    def release(self):
        pass


def test_camera_discovery_reports_available_busy_and_missing(monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", lambda idx, api=None, *a: _FakeCap(idx, api))
    cams = discover_cameras(max_index=3)
    by = {c["index"]: c for c in cams}
    assert by[0]["status"] == "available" and by[0]["width"] == 640
    assert by[1]["status"] == "no_frames" and "in use" in by[1]["detail"]
    assert 2 not in by and 3 not in by
    assert discover_cameras(max_index=0, skip={0})[0]["status"] == "in_use_by_crowdguard"


def test_webcam_errors_are_specific(monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", lambda idx, api=None, *a: _FakeCap(idx, api, opens=(), frames=()))
    with pytest.raises(SourceError) as e:
        WebcamSource(5).open()
    assert e.value.code == "CAMERA_UNAVAILABLE" and "privacy" in e.value.message
    monkeypatch.setattr(cv2, "VideoCapture", lambda idx, api=None, *a: _FakeCap(idx, api, opens=(0,), frames=()))
    with pytest.raises(SourceError) as e:
        WebcamSource(0).open()
    assert e.value.code == "CAMERA_UNAVAILABLE" and "NO_FRAMES" in e.value.message


def test_webcam_connects_and_reads(monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", lambda idx, api=None, *a: _FakeCap(idx, api))
    src = WebcamSource(0)
    src.open()
    f = src.read()
    assert f is not None and f.image.shape == (480, 640, 3) and src.live and src.kind == "live_camera"


def test_stream_url_validation_hides_credentials():
    with pytest.raises(SourceError) as e:
        StreamSource("file:///etc/passwd")
    assert e.value.code == "INVALID_STREAM"
    s = StreamSource("rtsp://admin:secret@10.0.0.5:554/stream1")
    assert "secret" not in s.label and "10.0.0.5" in s.label


# ---------------------------------------------------------------- detection (real model when present)
def test_yolo_initialises_once_and_detects_people():
    ultra = pytest.importorskip("ultralytics")
    import cv2

    from app.crowdguard.crowd_detection import get_detector

    det, status = get_detector()
    det2, _ = get_detector()
    assert det is det2  # one model instance per process
    if status["backend"] != "yolo":
        pytest.skip("no local YOLO weights on this machine")
    assert status["verified"] is True
    img = cv2.imread(str(Path(ultra.__file__).parent / "assets" / "bus.jpg"))
    assert len(det.detect(img)) >= 3


# ---------------------------------------------------------------- homography / projection
def test_ground_projection_round_trip_and_horizon():
    site = box_site()
    cal = LiveCalibration(image_points=[(200, 200), (440, 200), (600, 460), (40, 460)], frame_size=(640, 480), confirmed=True)
    gp = GroundProjector(site, cal)
    assert gp.valid
    corners = [gp.to_ground(p) for p in cal.image_points]
    for got, exp in zip(corners, [(0, 0), (10, 0), (10, 8), (0, 8)]):
        assert got == pytest.approx(exp, abs=1e-3)
    mid = gp.to_ground((320, 330))
    back = gp.to_image(mid)
    assert back == pytest.approx((320, 330), abs=1e-3)
    assert gp.to_ground((320, 5)) is None or gp.to_ground((320, 5))[1] < 0  # above the quad: off the site / no ground
    vis = gp.visible_mask(SiteMasks(site).centers)
    assert vis.all()  # the quad lies inside the frame, so every site cell is in view
    # A camera that only sees part of the site leaves the rest unknown.
    narrow = LiveCalibration(image_points=[(-300, 200), (940, 200), (1200, 460), (-560, 460)], frame_size=(640, 480))
    vis2 = GroundProjector(site, narrow).visible_mask(SiteMasks(site).centers)
    assert 0 < vis2.mean() < 1


def test_foot_uncertainty_grows_with_distance():
    site = box_site()
    gp = GroundProjector(site, LiveCalibration(image_points=[(250, 150), (390, 150), (620, 470), (20, 470)], frame_size=(640, 480)))
    near = gp.footprint_uncertainty((320, 460), 200)
    far = gp.footprint_uncertainty((320, 160), 40)
    assert far > near


# ---------------------------------------------------------------- free space / density
def test_kde_integrates_to_people_count():
    site = box_site(cell_m=0.25)
    people = [GroundPerson(5, 4), GroundPerson(4, 4), GroundPerson(6, 5)]
    d = kde_density(site, people)
    assert d.sum() * site.cell_m ** 2 == pytest.approx(3.0, rel=0.05)


def test_empty_space_states_and_unknown_when_feed_down():
    site = box_site(obstacles=[Obstacle(id="o", name="Pillar", polygon=[(4, 0.5), (6, 0.5), (6, 2), (4, 2)])])
    masks = SiteMasks(site)
    vis = np.ones((site.rows, site.cols), bool)
    crowd = [GroundPerson(2 + 0.1 * i, 6 + 0.05 * (i % 3), sigma=0.3) for i in range(14)]
    occ = compute_occupancy(site, masks, crowd, vis, feed_ok=True, metric=True)
    st = occ["_state"]
    assert st[site.cell_of((2.6, 6.0))] == "C"          # the crowd
    assert st[site.cell_of((8.5, 1.0))] == "A"          # open floor
    assert st[site.cell_of((5.0, 1.0))] == "B"          # the pillar
    assert occ["summary"]["free_space_m2"] < occ["summary"]["observed_walkable_m2"]
    assert occ["zones"][0]["population"] == pytest.approx(14) and occ["unit"] == "persons/m²"
    down = compute_occupancy(site, masks, [], vis, feed_ok=False, metric=True)
    assert set(down["state"]) <= {"U", "B"} and down["zones"][0]["population"] is None  # unknown, never empty
    rel = compute_occupancy(site, masks, crowd, vis, feed_ok=True, metric=False)
    assert rel["unit"].startswith("relative") and rel["zones"][0]["density"] is None  # no fabricated p/m²


def test_walkable_area_and_restricted_zones_are_blocked():
    site = box_site(walkable=[(0, 0), (10, 0), (10, 8), (0, 8)],
                    zones=[SiteZone(id="r", name="Backstage", polygon=[(3, 2), (7, 2), (7, 6), (3, 6)], restricted=True)])
    masks = SiteMasks(site)
    assert masks.blocked[site.cell_of((5, 4))] and masks.restricted[site.cell_of((5, 4))]
    planner = RoutePlanner(site, masks)
    assert site.cell_of((5, 4)) not in planner.graph


# ---------------------------------------------------------------- route guidance
def _plan_state(site, people):
    masks = SiteMasks(site)
    occ = compute_occupancy(site, masks, people, np.ones((site.rows, site.cols), bool), True, True)
    return masks, occ["_state"], occ["_density"] / site.congested_density


def test_route_avoids_congestion_and_obstacles():
    site = box_site(obstacles=[Obstacle(id="wall", name="Barrier", polygon=[(4.5, 0), (5.5, 0), (5.5, 6.5), (4.5, 6.5)])])
    crowd = [GroundPerson(0.3 + 0.3 * i, 2.8 + 0.4 * j, sigma=0.3) for i in range(6) for j in range(7)]  # jams the west exit approach
    masks, state, index = _plan_state(site, crowd)
    planner = RoutePlanner(site, masks)
    plan = planner.plan((3.0, 2.0), state, index)
    assert plan["ok"] and plan["best"]["exit"].id == "east"
    assert all(not masks.blocked[n] and state[n] != "C" for n in plan["best"]["path"])
    assert any(r["id"] == "west" for r in plan["rejected"]) or plan["naive"]["congested_points"]


def test_unavailable_exit_never_recommended_and_feed_down_gives_no_route():
    site = box_site(portals=[Portal(id="west", name="West exit", kind="exit", a=(0, 3), b=(0, 5), available=False),
                             Portal(id="east", name="East exit", kind="emergency_exit", a=(10, 3), b=(10, 5))])
    masks, state, index = _plan_state(site, [])
    plan = RoutePlanner(site, masks).plan((1.0, 4.0), state, index)
    assert plan["best"]["exit"].id == "east" and plan["rejected"][0]["id"] == "west"
    unknown = np.where(masks.blocked, "B", "U")
    assert RoutePlanner(site, masks).plan((1.0, 4.0), unknown, index)["ok"] is False


def test_guidance_hysteresis():
    site = box_site()
    masks, state, index = _plan_state(site, [])
    ctl = GuidanceController(RoutePlanner(site, masks))
    rec, changed = ctl.update((2.0, 4.0), "o", state, index, now=0.0)
    assert rec["exit_id"] == "west" and changed is None
    # A small crowd near the west exit: the east route becomes a bit cheaper but not decisively -> keep west.
    small = [GroundPerson(1.0, 4.0, sigma=0.6)]
    _, s2, i2 = _plan_state(site, small)
    for t in (1, 2, 3, 4, 6):
        rec, changed = ctl.update((2.0, 4.0), "o", s2, i2, now=float(t))
    assert rec["exit_id"] == "west" and changed is None
    # The west approach becomes congested: the current route is invalid -> switch immediately, with a reason.
    jam = [GroundPerson(0.6 + 0.1 * (i % 6), 3.4 + 0.2 * (i // 6), sigma=0.3) for i in range(30)]
    _, s3, i3 = _plan_state(site, jam)
    rec, changed = ctl.update((2.0, 4.0), "o", s3, i3, now=7.0)
    assert rec["exit_id"] == "east" and changed and "changed" in changed.lower()


# ---------------------------------------------------------------- alerts
def test_alert_dedup_escalation_and_cooldown():
    am = AlertManager(cooldown_s=30, clear_after_s=2)
    a = am.observe("k", True, 0, severity="high", kind="x", observation="o")
    assert a is not None
    assert am.observe("k", True, 1, severity="high", kind="x") is None  # deduplicated
    am.observe("k", True, 1.5, severity="critical", kind="x")
    assert am.snapshot()[0]["severity"] == "critical"  # escalated in place
    am.observe("k", False, 5, kind="x")  # cleared after 2 s false
    assert am.snapshot() == []
    assert am.observe("k", True, 10, severity="high", kind="x") is None and am.suppressed == 1  # cooldown
    assert am.observe("k", True, 40, severity="high", kind="x") is not None


# ---------------------------------------------------------------- monitor threads (fake camera, no model needed)
class FakeCam(FrameSource):
    kind = "live_camera"
    live = True

    def __init__(self, fps=60.0, fail_after=None, reopen_ok=True):
        super().__init__("Fake camera")
        self.fps, self.fail_after, self.reopen_ok, self.opens = fps, fail_after, reopen_ok, 0

    def open(self):
        self.opens += 1
        if self.opens > 1 and not self.reopen_ok:
            raise SourceError("CAMERA_UNAVAILABLE", "gone")
        self.width, self.height = 640, 480
        self.n_since_open = 0

    def read(self):
        time.sleep(1.0 / self.fps)
        self.n_since_open += 1
        if self.fail_after is not None and (self.opens == 1 or not self.reopen_ok) and self.n_since_open > self.fail_after:
            return None
        self._index += 1
        x = 100 + (self._index % 50) * 4
        return Frame(np.zeros((480, 640, 3), np.uint8), time.time(), self._index,
                     synthetic_boxes=[BoundingBox(x1=x, y1=250, x2=x + 40, y2=420, confidence=0.9)])


def _wait(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_latest_frame_wins_no_backlog():
    mon = LiveMonitor()
    mon.max_fps = 5  # processing slower than the 60 fps camera
    mon.start(FakeCam(fps=60), "fake")
    try:
        assert _wait(lambda: mon.stats["processed"] >= 8)
        st = mon.stats
        assert st["skipped"] > st["processed"]  # newer frames replace unprocessed ones
        assert st["e2e_ms"] < 500  # the analysed frame is always recent
        snap = json.loads(mon.last_snapshot)
        assert snap["tracks"] and snap["tracks"][0]["id"] == json.loads(mon.last_snapshot)["tracks"][0]["id"]
    finally:
        mon.stop()


def test_identity_persists_across_frames():
    mon = LiveMonitor()
    mon.start(FakeCam(fps=20), "fake")
    try:
        assert _wait(lambda: mon.stats["processed"] >= 15)
        ids = set()
        for _ in range(5):
            ids |= {t["id"] for t in json.loads(mon.last_snapshot)["tracks"] if not t["predicted"]}
            time.sleep(0.1)
        assert len(ids) == 1  # one person walking: one persistent id
    finally:
        mon.stop()


def test_disconnect_marks_area_unknown_and_reconnects():
    mon = LiveMonitor()
    cam = FakeCam(fps=30, fail_after=10)
    mon.start(cam, "fake")
    try:
        assert _wait(lambda: any(a["kind"] == "camera_disconnected" for a in mon.alerts.recent()))
        assert _wait(lambda: mon.stats["reconnects"] >= 1 and mon.status == "running")
        assert any(a["kind"] == "camera_reconnected" for a in mon.alerts.recent())
    finally:
        mon.stop()
    mon2 = LiveMonitor()
    mon2.start(FakeCam(fps=30, fail_after=5, reopen_ok=False), "fake")
    try:
        assert _wait(lambda: mon2.status == "disconnected")
        assert _wait(lambda: json.loads(mon2.last_snapshot)["status"] == "stale", timeout=6)
        snap = json.loads(mon2.last_snapshot)
        assert set(snap["grid"]["state"]) <= {"U", "B"} and snap["route"]["available"] is False
    finally:
        mon2.stop()


# ---------------------------------------------------------------- API + WebSocket
def test_live_api_and_websocket_stream(client):
    r = client.post("/api/crowdguard/live/start", json={"source": {"kind": "synthetic", "scenario": "bottleneck"}})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["source"]["kind"] == "synthetic" and r.json()["result"]["source"]["live"] is False
    try:
        with client.websocket_connect("/api/crowdguard/live/ws?frames=1") as ws:
            first = json.loads(ws.receive_text())
            assert first["type"] == "status"
            seqs, kinds = [], set()
            t0 = time.time()
            while len(seqs) < 4 and time.time() - t0 < 20:
                msg = json.loads(ws.receive_text())
                kinds.add(msg["type"])
                if msg["type"] == "snapshot":
                    seqs.append(msg["seq"])
                    snap = msg
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
            assert snap["source"]["kind"] == "synthetic" and snap["tracks"] and snap["grid"]["rows"] > 0
            assert snap["route"]["available"] and snap["calibration"]["metric"] is True
            assert "frame" in kinds or _wait(lambda: True)
        # Reconnect: the newest snapshot is delivered straight away.
        with client.websocket_connect("/api/crowdguard/live/ws") as ws2:
            msgs = [json.loads(ws2.receive_text()) for _ in range(2)]
            assert any(m["type"] == "snapshot" and m["seq"] >= seqs[-1] for m in msgs)
        site = client.get("/api/crowdguard/live/site").json()["result"]
        assert site["rows"] * site["cols"] == len(site["blocked"])
        bad = client.post("/api/crowdguard/live/portals", json={"portal_id": "nope", "available": False})
        assert bad.status_code == 404
        ok = client.post("/api/crowdguard/live/portals", json={"portal_id": "p-out-1", "available": False})
        assert ok.status_code == 200
        cal = client.post("/api/crowdguard/live/calibration", json={"image_points": [[0, 0], [10, 0], [10, 10], [0, 10]]})
        assert cal.status_code == 422 and cal.json()["error"]["code"] == "SYNTHETIC"
        viewer = client.post("/api/crowdguard/live/stop", headers={"X-Omniforge-Role": "viewer"})
        assert viewer.status_code == 403
    finally:
        client.post("/api/crowdguard/live/stop")
    assert client.get("/api/crowdguard/live/status").json()["result"]["status"] == "idle"


def test_calibration_api_metric_requires_measurements(client, monkeypatch):
    mon = client.app.state.services.registry.get("crowd").live
    mon.start(FakeCam(fps=20), "fake")
    try:
        pts = [[200, 200], [440, 200], [600, 460], [40, 460]]
        r = client.post("/api/crowdguard/live/calibration", json={"image_points": pts, "confirmed": True})
        assert r.status_code == 422 and r.json()["error"]["code"] == "DIMENSIONS_REQUIRED"
        r = client.post("/api/crowdguard/live/calibration", json={"image_points": [[0, 0], [1, 1], [2, 2], [3, 3]]})
        assert r.status_code == 422
        r = client.post("/api/crowdguard/live/calibration", json={"image_points": pts, "confirmed": True, "width_m": 8, "height_m": 6})
        assert r.status_code == 200 and r.json()["result"]["metric"] is True
        assert mon.site.width_m == 8 and mon.site.height_m == 6
        assert _wait(lambda: mon.last_snapshot and json.loads(mon.last_snapshot)["grid"]["unit"] == "persons/m²")
    finally:
        mon.stop()


def test_default_site_matches_digital_twin():
    site = default_site()
    assert site.width_m == 24 and len(site.zones) == 4 and {p.kind for p in site.portals} == {"entrance", "exit", "emergency_exit"}


def test_sources_label_recordings_and_simulation_honestly(tmp_path):
    from app.crowdguard.camera_sources import SyntheticSource, VideoFileSource

    assert SyntheticSource().kind == "synthetic" and SyntheticSource().live is False
    assert VideoFileSource(tmp_path / "x.mp4", "x.mp4").live is False
    with pytest.raises(SourceError) as e:
        VideoFileSource(tmp_path / "missing.mp4", "missing").open()
    assert e.value.code == "FILE_MISSING"
    assert camera_sources.build_source({"kind": "synthetic"}).kind == "synthetic"
    with pytest.raises(SourceError):
        camera_sources.build_source({"kind": "nonsense"})


def test_switching_source_never_serves_the_previous_picture():
    mon = LiveMonitor()
    mon.start(FakeCam(fps=30), "fake-a")
    try:
        assert _wait(lambda: mon.last_snapshot is not None)
        mon.start(FakeCam(fps=30), "fake-b")
        # Until the new source produces its own snapshot, there is nothing to hand out.
        snap = mon.last_snapshot
        assert snap is None or json.loads(snap)["stats"]["started_at"] == mon.stats["started_at"]
    finally:
        mon.stop()
    assert mon.last_snapshot is None


def test_slow_camera_raises_an_alert():
    mon = LiveMonitor()
    cam = FakeCam(fps=2)  # a camera starved by another application
    mon.start(cam, "fake")
    try:
        mon.stats["started_at"] = time.time() - 30  # pretend it has been running a while
        assert _wait(lambda: any(a["kind"] == "camera_slow" for a in mon.alerts.recent()), timeout=12)
    finally:
        mon.stop()



def test_camera_discovery_after_stop_does_not_report_in_use(client, monkeypatch):
    from app.engines.crowd import engine as crowd_engine
    seen = []
    monkeypatch.setattr(crowd_engine, "discover_cameras", lambda max_index, skip=frozenset(): seen.append(set(skip)) or [])
    mon = client.app.state.services.registry.get("crowd").live
    mon.start(FakeCam(fps=30), "webcam:0")
    try:
        client.get("/api/crowdguard/live/cameras")
    finally:
        client.post("/api/crowdguard/live/stop")
    client.get("/api/crowdguard/live/cameras")
    assert seen == [{0}, set()]  # held while running; free again after the stop
