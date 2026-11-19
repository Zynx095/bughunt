"""CROWDGUARD: zones, estimation, alerts, flow, forecasting, routing, feeds, incidents, media and API."""
from __future__ import annotations

import copy
import time
from pathlib import Path

import pytest
from sqlalchemy import update

from app.crowdguard.congestion_detector import default_rules, detect, local_evaluator, zone_facts
from app.crowdguard.crowd_detection import Detection, find_weights
from app.crowdguard.crowd_flow import trend_per_minute, track_velocities, walking_speed
from app.crowdguard.crowd_forecaster import forecast_zone, rolling_backtest
from app.crowdguard.crowd_tracking import IoUTracker, TrackHistory
from app.crowdguard.density_estimator import Observation, assess_reading, occlusion_corrected
from app.crowdguard.route_optimizer import RouteOptimizer, RouteState
from app.crowdguard.safety_recommendations import validate_action
from app.crowdguard.simulation import ScenarioConfig, run_scenario
from app.crowdguard.venue import load_venue
from app.crowdguard.zone_manager import ZoneManager, point_in_polygon, polygon_area
from app.db.models import CrowdIncident

VENUE = load_venue()
SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]


def reading(zone_id: str, pct: float, feed: str = "ok", **kw) -> dict:
    z = VENUE.zones.get(zone_id)
    est = int(z.safe_capacity * pct / 100)
    obs = Observation(zone_id=zone_id, t=0, feed_status=feed, observed_count=est if feed == "ok" else None,
                      detector_confidence=0.9, source="manual", value_kind="measured")
    r = assess_reading(z, obs, None, VENUE.thresholds)
    if feed == "ok":  # pin the estimate to the requested level for routing tests
        r.update(estimate=est, lower=int(est * 0.95), upper=int(est * 1.05), occupancy_pct=round(pct, 1),
                 upper_pct=round(pct * 1.05, 1), density_ppm2=round(est / z.area_m2, 3))
        from app.crowdguard.density_estimator import occupancy_band
        r["band"] = occupancy_band(pct, r["density_ppm2"], VENUE.thresholds)
    r.update(kw)
    return r


def state(levels: dict[str, float], **kw) -> RouteState:
    zones = {z.id: reading(z.id, levels.get(z.id, 30.0)) for z in VENUE.zones.zones}
    return RouteState(zones=zones, **kw)


# ---------------------------------------------------------------- zones & polygons
def test_polygon_assignment_and_boundaries():
    assert point_in_polygon((5, 5), SQUARE) and not point_in_polygon((11, 5), SQUARE)
    assert point_in_polygon((10, 5), SQUARE) and point_in_polygon((0, 0), SQUARE)  # edge and vertex count as inside
    tri = [[0, 0], [10, 0], [0, 10]]
    assert point_in_polygon((2, 2), tri) and not point_in_polygon((8, 8), tri)
    assert polygon_area(SQUARE) == 100


def test_zone_population_counts_overlaps_and_unzoned():
    zm = ZoneManager.from_config([
        {"id": "big", "name": "Big", "polygon": SQUARE, "area_m2": 100, "safe_capacity": 200},
        {"id": "inner", "name": "Inner", "polygon": [[2, 2], [4, 2], [4, 4], [2, 4]], "area_m2": 4, "safe_capacity": 8},
    ])
    counts = zm.count([(3, 3), (3.5, 2.5), (8, 8), (50, 50)])
    assert counts == {"big": 1, "inner": 2, ZoneManager.UNZONED: 1}  # smallest (most specific) zone wins
    with pytest.raises(ValueError):
        ZoneManager.from_config([{"id": "bad", "polygon": [[0, 0], [1, 1]], "area_m2": 1, "safe_capacity": 1}])


def test_venue_graph_is_valid():
    assert VENUE.graph.number_of_nodes() == len(VENUE.nodes) and VENUE.is_emergency_exit("exit_east")
    assert not VENUE.is_emergency_exit("gate_north")
    assert all(e["capacity_ppm"] > 0 for e in VENUE.edges.values())


# ---------------------------------------------------------------- estimation & feeds
def test_occlusion_correction_has_interval_and_never_undercounts_observed():
    c = occlusion_corrected(300, 100)
    assert c["estimate"] > 300 and c["lower"] >= 300 and c["upper"] > c["estimate"]
    assert occlusion_corrected(0, 100)["estimate"] == 0


def test_missing_feed_is_unknown_not_zero():
    z = VENUE.zones.get("food_court")
    none_yet = assess_reading(z, Observation("food_court", 60, feed_status="missing"), None)
    assert none_yet["estimate"] is None and none_yet["band"] == "unknown" and none_yet["occupancy_pct"] is None
    assert none_yet["data_quality"] == "unavailable"
    live = assess_reading(z, Observation("food_court", 0, observed_count=1500, detector_confidence=0.9), None)
    stale = assess_reading(z, Observation("food_court", 120, feed_status="stale"), live)
    assert stale["estimate"] == live["estimate"] and stale["carried_forward"] and stale["age_s"] == 120
    assert stale["upper"] > live["upper"] and stale["confidence"] < live["confidence"]  # uncertainty grows with age
    failed = assess_reading(z, Observation("food_court", 60, feed_status="detector_error"), None)
    assert failed["estimate"] is None and "detection failed" in failed["notes"][0]
    zero = assess_reading(z, Observation("food_court", 0, observed_count=0, detector_confidence=0.9), None)
    assert zero["estimate"] == 0 and zero["band"] == "normal" and zero["feed_status"] == "ok"  # measured zero


# ---------------------------------------------------------------- alerts
def _alerts_for(zone_id: str, pct: float, **extra):
    z = VENUE.zones.get(zone_id)
    r = reading(zone_id, pct)
    f = zone_facts(z, r, growth_pct_per_min=extra.get("growth"), flow=extra.get("flow"), forecast=extra.get("forecast"))
    return detect([f], default_rules(VENUE.thresholds), local_evaluator())


def test_capacity_thresholds():
    assert {a["type"] for a in _alerts_for("main_stage", 60)} == set()
    near = _alerts_for("main_stage", 88)
    assert [a["type"] for a in near] == ["near_capacity"] and near[0]["severity"] == "high"
    over = _alerts_for("main_stage", 104)
    assert over[0]["type"] == "overcrowded" and over[0]["severity"] == "critical"


def test_rapid_increase_forecast_queue_and_stale_rules():
    rapid = {a["type"] for a in _alerts_for("main_stage", 70, growth=2.5)}
    assert "rapid_build_up" in rapid
    fc = {"available": True, "minutes_to_capacity": 9.0, "peak_pct": 104}
    assert "forecast_capacity_breach" in {a["type"] for a in _alerts_for("main_stage", 75, forecast=fc)}
    q = {a["type"] for a in _alerts_for("bar_queue", 80)}  # 480 people at 40/min service = 12 min wait
    assert "slow_moving_queue" in q
    z = VENUE.zones.get("food_court")
    stale = assess_reading(z, Observation("food_court", 60, feed_status="stale"), None)
    alerts = detect([zone_facts(z, stale, growth_pct_per_min=None, flow=None, forecast=None)], default_rules(VENUE.thresholds), local_evaluator())
    assert [a["type"] for a in alerts] == ["stale_feed"] and "unknown" in alerts[0]["message"]


# ---------------------------------------------------------------- flow & tracking
def test_movement_rate_and_direction():
    h = TrackHistory()
    for i in range(6):
        h.add(1, i * 0.2, 100 + 10 * i * 0.2, 50, "a")   # 10 px/s east
        h.add(2, i * 0.2, 300, 200 - 5 * i * 0.2, "a")   # 5 px/s up = north
    v = {x["track_id"]: x for x in track_velocities(h)}
    assert v[1]["speed"] == pytest.approx(10, rel=1e-3) and 359 <= v[1]["heading_deg"] or v[1]["heading_deg"] <= 1
    assert v[2]["heading_deg"] == pytest.approx(90, abs=0.5) and v[2]["unit"] == "px/s"
    vm = {x["track_id"]: x for x in track_velocities(h, meters_per_pixel=0.02)}
    assert vm[1]["speed"] == pytest.approx(0.2, rel=1e-3) and vm[1]["unit"] == "m/s"
    assert trend_per_minute([50, 52, 54, 56, 58]) == pytest.approx(2.0)
    assert walking_speed(0.5) > walking_speed(3.0) > walking_speed(5.0)


def test_tracker_counts_each_person_once():
    tr = IoUTracker(min_hits=1)
    hist = TrackHistory()
    for f in range(10):
        dets = [Detection(10 + 2 * f, 10, 40 + 2 * f, 90, 0.9), Detection(200 - 3 * f, 20, 230 - 3 * f, 100, 0.8)]
        for o in tr.update(dets, f * 0.1):
            hist.add(o.track_id, f * 0.1, *o.foot, "z")
    assert hist.unique_ids() == [1, 2] and hist.fragmentation() == 0  # 20 detections, 2 people


# ---------------------------------------------------------------- forecasting
def test_forecast_methods_and_capacity_prediction():
    rising = [5450 + 150 * i for i in range(20)]  # ends at 8300 of 9000
    fc = forecast_zone(rising, 9000, horizon=15)
    assert fc["method"] == "damped Holt trend" and fc["minutes_to_capacity"] is not None
    assert fc["predicted_end"] > fc["current"] and all(lo <= p <= hi for lo, p, hi in zip(fc["lower"], fc["forecast"], fc["upper"]))
    widths = [hi - lo for lo, hi in zip(fc["lower"], fc["upper"])]
    assert widths[-1] > widths[0]  # uncertainty grows with the horizon
    assert forecast_zone(rising, 9000) == fc  # deterministic
    short = forecast_zone([4000, 4100], 9000)
    assert short["method"].startswith("persistence") and short["forecast"][-1] == 4100
    assert forecast_zone([], 9000)["available"] is False
    bt = rolling_backtest(rising + [rising[-1] + 150 * i for i in range(1, 15)], 9000, horizon=5)
    assert bt["available"] and bt["beats_baseline"]


# ---------------------------------------------------------------- routing
def test_alternative_route_avoids_overcrowded_zones_and_rejects_shortest():
    planner = RouteOptimizer(VENUE)
    st = state({"main_stage": 104, "food_court": 92, "second_stage": 40})
    plan = planner.plan(st, "main_stage", "relieve", 600)
    rec = plan["recommended"]
    assert rec and rec["destination"] == "second_stage"
    for n in rec["path"][1:]:
        assert st.zones.get(n, {}).get("band") not in ("high", "critical")
    # The distance-shortest relief target (Food Court) is overcrowded: it is assessed and rejected, with reasons.
    assert plan["shortest_path"]["destination"] == "food_court" and plan["shortest_path"]["safe"] is False
    assert any("rejected" in e for e in plan["explanation"])
    assert any(d["id"] == "food_court" for d in plan["rejected_destinations"])


def test_blocked_routes_and_exits_are_avoided():
    planner = RouteOptimizer(VENUE)
    free = planner.plan(state({}), "east_concourse", "egress", 200)
    assert free["recommended"]["destination"] == "exit_east"
    blocked = planner.plan(state({}, blocked_nodes={"exit_east"}), "east_concourse", "egress", 200)
    assert blocked["recommended"]["destination"] != "exit_east"
    assert "exit_east" not in blocked["recommended"]["path"]
    assert blocked["shortest_path"]["safe"] is False and any("blocked" in e for e in blocked["explanation"])
    edge_blocked = planner.plan(state({}, blocked_edges={"e_js_ss"}), "main_stage", "relieve", 300)
    assert "e_js_ss" not in edge_blocked["recommended"]["edges"]


def test_destination_capacity_validation_and_split_allocation():
    planner = RouteOptimizer(VENUE)
    st = state({"main_stage": 105, "second_stage": 75, "food_court": 50})
    plan = planner.plan(st, "main_stage", "relieve", 2000)
    total = sum(a["people"] for a in plan["allocation"]) + plan["unallocated"]
    assert total == 2000
    for a in plan["allocation"]:  # no destination is pushed above the 85 % limit
        z = VENUE.zones.get(a["destination"])
        assert st.zones[a["destination"]]["upper"] + a["people"] <= z.safe_capacity * 0.85 + 1
    full = planner.plan(state({"main_stage": 105, "second_stage": 84, "food_court": 84}), "main_stage", "relieve", 500)
    assert full["recommended"] is None and "Do not move people" in full["explanation"][0]


def test_stale_destination_is_not_used():
    st = state({"main_stage": 104, "food_court": 40, "second_stage": 40})
    st.zones["food_court"].update(feed_status="stale", carried_forward=True)
    plan = RouteOptimizer(VENUE).plan(st, "main_stage", "relieve", 400)
    assert plan["recommended"]["destination"] == "second_stage"
    assert any(d["id"] == "food_court" and "unverified" in d["reason"] for d in plan["rejected_destinations"])


def test_emergency_exits_can_never_be_restricted():
    ok, why = validate_action({"action_type": "meter_entry", "target": "exit_east"}, VENUE)
    assert not ok and "emergency exit" in why
    assert validate_action({"action_type": "meter_entry", "target": "gate_north"}, VENUE)[0]
    assert validate_action({"action_type": "clear_exit_obstruction", "target": "exit_east"}, VENUE)[0]


# ---------------------------------------------------------------- simulation
def test_simulation_is_deterministic_and_tells_the_story():
    a = run_scenario(VENUE, ScenarioConfig(), local_evaluator())
    b = run_scenario(VENUE, ScenarioConfig(), local_evaluator())
    assert a["frames"][40]["readings"] == b["frames"][40]["readings"]
    m = a["evaluation"]["milestones"]
    assert m["first_forecast_breach_alert"]["tick"] <= m["first_overcrowded_alert"]["tick"]
    assert m["first_relief_route"] is not None and m["exit_blocked_alert"] and m["stale_feed_alert"]
    assert a["counterfactual"]["peak_pct"] > a["evaluation"]["main_stage_peak"]["pct"]
    statuses = [e["status"] for e in a["incidents"][0]["events"]]
    assert statuses[0] == "detected" and "responding" in statuses and statuses[-1] == "resolved"
    for f in a["frames"]:  # a stale feed is never reported as an empty zone
        fc = f["readings"]["food_court"]
        if fc["feed_status"] != "ok":
            assert fc["estimate"] is None or fc["carried_forward"]
        for r in f["recommendations"]:
            assert r["permitted"] and r["requires_human_decision"]
    assert a["scenario"]["label"].startswith("SYNTHETIC")


# ---------------------------------------------------------------- API
def test_api_venue_simulation_route_forecast(client):
    v = client.get("/api/crowdguard/venue").json()
    assert v["success"] and len(v["result"]["zones"]) == 8
    sim = client.post("/api/crowdguard/simulation", json={"tick": 38}).json()
    assert sim["success"] and sim["result"]["frame"]["tick"] == 38 and any("SYNTHETIC" in w for w in sim["warnings"])
    r = client.post("/api/crowdguard/route", json={"source": "main_stage", "group_size": 800, "tick": 38}).json()
    assert r["success"] and r["result"]["recommended"]
    bad = client.post("/api/crowdguard/route", json={"source": "nowhere"})
    assert bad.status_code == 422
    fc = client.post("/api/crowdguard/forecast", json={"zone_id": "main_stage", "tick": 34}).json()
    assert fc["success"] and fc["result"]["ml_engine"]["backtest"] and fc["result"]["deterministic"]["available"]
    short = client.post("/api/crowdguard/forecast", json={"zone_id": "main_stage", "history": [100, 120, 140]}).json()
    assert short["result"]["ml_engine"] is None and any("fallback" in w for w in short["warnings"])


def test_api_assess_marks_missing_zones_unknown(client):
    body = {"observations": [{"zone_id": "main_stage", "observed_count": 7800, "detector_confidence": 0.8}]}
    res = client.post("/api/crowdguard/assess", json=body).json()
    assert res["success"]
    zones = res["result"]["readings"]
    assert zones["main_stage"]["estimate"] > 7800 and zones["food_court"]["band"] == "unknown"
    assert zones["food_court"]["estimate"] is None  # never zero
    assert any(a["type"] == "stale_feed" and a["target"] == "food_court" for a in res["result"]["alerts"])
    assert res["result"]["summary"]["zones_without_live_data"] == 7


def test_incident_lifecycle_four_eyes_and_tamper_detection(client, tmp_path):
    h1 = {"X-Omniforge-Actor": "steward-1"}
    inc = client.post("/api/crowdguard/incidents", json={"title": "Main Stage build-up", "zone_id": "main_stage",
                                                         "severity": "critical", "evidence": {"pct": 104}}, headers=h1).json()
    assert inc["success"], inc
    iid = inc["result"]["id"]
    act = lambda a, h=h1: client.post(f"/api/crowdguard/incidents/{iid}/actions", json={"action": a, "note": a}, headers=h)  # noqa: E731
    assert act("close").status_code == 409  # cannot close before resolving
    for a in ("acknowledge", "respond", "resolve"):
        assert act(a).json()["success"]
    assert act("close").status_code == 403  # four-eyes: opener cannot close
    ai = client.post(f"/api/crowdguard/incidents/{iid}/actions", json={"action": "note"}, headers={"X-Omniforge-Actor-Type": "ai"})
    assert ai.status_code == 403
    closed = act("close", {"X-Omniforge-Actor": "safety-officer", "X-Omniforge-Role": "reviewer"}).json()
    assert closed["success"] and closed["result"]["status"] == "closed" and closed["result"]["sealed_root"]
    ver = client.get(f"/api/crowdguard/incidents/{iid}/verify").json()["result"]
    assert ver["valid"] and len(ver["checks"]) == 3
    store = client.app.state.services.store
    with store.session() as s:
        row = s.get(CrowdIncident, iid)
        events = copy.deepcopy(row.events)
        events[1]["note"] = "edited after the fact"
        s.execute(update(CrowdIncident).where(CrowdIncident.id == iid).values(events=events))
    ver2 = client.get(f"/api/crowdguard/incidents/{iid}/verify").json()["result"]
    assert ver2["valid"] is False
    audit = client.get("/api/audit?category=incident").json()
    assert {"incident_opened", "self_close_blocked", "incident_close"} <= {e["action"] for e in audit}


def test_media_upload_rejects_non_media(client):
    r = client.post("/api/crowdguard/media", files={"file": ("x.mp4", b"MZ\x90\x00not a video", "video/mp4")})
    assert r.status_code == 415
    viewer = client.post("/api/crowdguard/media", files={"file": ("x.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
                         headers={"X-Omniforge-Role": "viewer"})
    assert viewer.status_code == 403


def _wait(client, job_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/crowdguard/media/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.5)
    raise AssertionError("media job timed out")


def test_image_and_video_ingestion(client):
    """Real detection on the Ultralytics sample photo (YOLO if local weights exist, otherwise OpenCV HOG)."""
    ultra = pytest.importorskip("ultralytics")
    img = Path(ultra.__file__).parent / "assets" / "bus.jpg"
    r = client.post("/api/crowdguard/media", files={"file": ("bus.jpg", img.read_bytes(), "image/jpeg")},
                    data={"layout": "single_zone", "venue_zone": "north_plaza", "coverage": "0.05"})
    assert r.status_code == 200, r.text
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "completed", job
    res = job["response"]["result"]
    assert res["kind"] == "image" and res["quality"]["frames_ok"] == 1
    if res["detector"]["backend"] == "yolo":
        assert res["zones"][0]["current_observed"] >= 3  # the photo shows four people
    assert res["venue_observations"][0]["zone_id"] == "north_plaza"
    vid = client.post("/api/crowdguard/media/sample", json={"layout": "default_two_zone"}).json()
    job = _wait(client, vid["job_id"])
    assert job["status"] == "completed", job
    res = job["response"]["result"]
    assert res["kind"] == "video" and res["quality"]["frames_processed"] >= 10 and res["keyframes"]
    if res["detector"]["backend"] == "yolo":
        # ~4 people visible in every frame: tracking keeps unique ids close to that, not frames × people.
        assert 3 <= res["totals"]["unique_people"] <= 8
        assert res["flow"]["overall"]["dominant_direction"] in ("W", "SW", "NW")  # camera pans east, scene moves west
    assert "artificial" in vid["provenance"]["label"]


def test_crowd_pipeline_run(client):
    run = client.post("/api/domains/crowd_safety/run", json={}).json()
    assert run["status"] == "completed", run.get("error")
    steps = {s["id"]: s["status"] for s in run["steps"]}
    assert steps["snapshot"] == steps["risk"] == steps["route"] == steps["seal"] == "completed"
    assert run["presentation"]["tables"][0]["rows"]


def test_yolo_weights_discovery_reports_search_paths():
    path, searched = find_weights("Z:/definitely/missing.pt")
    assert searched[0].endswith("missing.pt")
    assert path is None or path.is_file()
