# CROWDGUARD — automated test results

Recorded on the build machine on 2026-11-19 (Windows 11, Python 3.12.0, Node v26.7.0). These are copied from actual runs; nothing was
edited by hand. Re-run them with the commands shown. The full-suite block and the real-time sections are from branch
`feature/crowdguard-realtime-ux`; the per-file verbose listings further down were recorded earlier on `integration/omniforge-final`.

## Backend: full suite

```
$ cd backend && python -m pytest -o addopts="" -q
145 passed

tests/test_ai.py                10 passed
tests/test_api.py               25 passed   (incl. the parametrised pipeline test for all 10 adapters)
tests/test_crowdguard.py        23 passed
tests/test_crowdguard_live.py   24 passed   (real-time pipeline, new on this branch)
tests/test_crowdguard_vcie.py   19 passed   (12 VCIE tests + 7 integration tests)
tests/test_crypto.py            18 passed
tests/test_decision.py           5 passed
tests/test_ml_data.py           13 passed
tests/test_security.py           8 passed
```

Changes to existing tests (nothing was deleted or loosened):
* `test_health_and_engines` expects seven engines (the original six plus `crowd`).
* The three VCIE API tests use the isolated `client` fixture (temporary database) instead of the module-level app, and read the
  standard envelope (`response.json()["result"]`) because these routes now go through the engine registry. Their assertions are unchanged,
  except that the step test now also checks that all five views come back together and that the frame is labelled `synthetic`.

## Backend: CROWDGUARD tests (`tests/test_crowdguard.py`, verbose)

```
test_polygon_assignment_and_boundaries PASSED  [  4%]
test_zone_population_counts_overlaps_and_unzoned PASSED [  8%]
test_venue_graph_is_valid PASSED               [ 13%]
test_occlusion_correction_has_interval_and_never_undercounts_observed PASSED [ 17%]
test_missing_feed_is_unknown_not_zero PASSED   [ 21%]
test_capacity_thresholds PASSED                [ 26%]
test_rapid_increase_forecast_queue_and_stale_rules PASSED [ 30%]
test_movement_rate_and_direction PASSED        [ 34%]
test_tracker_counts_each_person_once PASSED    [ 39%]
test_forecast_methods_and_capacity_prediction PASSED [ 43%]
test_alternative_route_avoids_overcrowded_zones_and_rejects_shortest PASSED [ 47%]
test_blocked_routes_and_exits_are_avoided PASSED [ 52%]
test_destination_capacity_validation_and_split_allocation PASSED [ 56%]
test_stale_destination_is_not_used PASSED      [ 60%]
test_emergency_exits_can_never_be_restricted PASSED [ 65%]
test_simulation_is_deterministic_and_tells_the_story PASSED [ 69%]
test_api_venue_simulation_route_forecast PASSED [ 73%]
test_api_assess_marks_missing_zones_unknown PASSED [ 78%]
test_incident_lifecycle_four_eyes_and_tamper_detection PASSED [ 82%]
test_media_upload_rejects_non_media PASSED     [ 86%]
test_image_and_video_ingestion PASSED          [ 91%]
test_crowd_pipeline_run PASSED                 [ 95%]
test_yolo_weights_discovery_reports_search_paths PASSED [100%]
============================= 23 passed in 7.27s ==============================
```

| Requirement | Test(s) |
|---|---|
| Zone population calculation | `test_zone_population_counts_overlaps_and_unzoned` |
| Polygon-based zone assignment | `test_polygon_assignment_and_boundaries`, `test_zone_population_counts_overlaps_and_unzoned` |
| Capacity threshold detection | `test_capacity_thresholds`, `test_rapid_increase_forecast_queue_and_stale_rules` |
| Movement-rate calculation | `test_movement_rate_and_direction` |
| No double counting across frames | `test_tracker_counts_each_person_once`, `test_image_and_video_ingestion` |
| Forecasting | `test_forecast_methods_and_capacity_prediction`, `test_api_venue_simulation_route_forecast` |
| Alternative path selection | `test_alternative_route_avoids_overcrowded_zones_and_rejects_shortest` |
| Blocked route handling | `test_blocked_routes_and_exits_are_avoided` |
| Destination capacity validation | `test_destination_capacity_validation_and_split_allocation`, `test_stale_destination_is_not_used` |
| Missing video feeds | `test_missing_feed_is_unknown_not_zero`, `test_api_assess_marks_missing_zones_unknown` |
| Emergency exits never restricted | `test_emergency_exits_can_never_be_restricted` |
| Deterministic demonstration | `test_simulation_is_deterministic_and_tells_the_story` |
| API integration | `test_api_*`, `test_incident_lifecycle_four_eyes_and_tamper_detection`, `test_media_upload_rejects_non_media`, `test_crowd_pipeline_run` |
| Image/video ingestion | `test_image_and_video_ingestion` (YOLO on the Ultralytics sample photo + synthesised pan clip) |

`test_image_and_video_ingestion` adapts to the machine it runs on. With local YOLO weights (as on the build machine) it also asserts
that at least 3 of the 4 people in the photo are detected, that the unique track count is between 3 and 8, and that the motion is westward. With the HOG fallback it only
asserts that the job completes.

## Backend: VCIE and integration tests (`tests/test_crowdguard_vcie.py`, verbose)

```
test_homography_calculation_and_projection PASSED [  5%]
test_degenerate_and_collinear_calibration_handling PASSED [ 10%]
test_order_points_clockwise PASSED        [ 15%]
test_ground_contact_point_extraction PASSED [ 21%]
test_detection_fallback_and_projection PASSED [ 26%]
test_multi_object_tracker_persistence PASSED [ 31%]
test_gaussian_kde_density_calculation PASSED [ 36%]
test_heatmap_render_modes PASSED          [ 42%]
test_movement_vector_and_bottleneck_detection PASSED [ 47%]
test_api_crowdguard_presets PASSED        [ 52%]
test_api_crowdguard_calibration_endpoint PASSED [ 57%]
test_api_crowdguard_simulation_step_and_images PASSED [ 63%]
test_vcie_uses_the_single_offline_detector PASSED [ 68%]
test_detection_failure_is_not_an_empty_scene PASSED [ 73%]
test_bytetrack_identity_drives_ground_plane_tracks PASSED [ 78%]
test_zone_risk_uses_shared_occupancy_thresholds PASSED [ 84%]
test_api_operator_calibration_validation PASSED [ 89%]
test_api_removed_arbitrary_path_ingestion PASSED [ 94%]
test_api_video_job_returns_synchronised_views PASSED [100%]
```

## Frontend

```
$ cd frontend && npm run build      # tsc -b && vite build  → ✓ built (exit 0)
$ cd frontend && npm run lint       # oxlint → 0 warnings, 0 errors
```

## End-to-end demonstration (live server, `integration/omniforge-final`)

Run against `uvicorn app.main:app --port 8010`, which serves the built UI, through HTTP:

```
PASS 1 start engines=['ai', 'crowd', 'crypto', 'data', 'decision', 'ml', 'security']
PASS 2 UI served
PASS 3 synthetic festival (66 frames, labelled SYNTHETIC)
PASS 4 zone occupancy Main Stage 9372 (8331-10643) 104.1% critical
PASS 5 congestion event build-up 18:20, forecast 18:32, overcrowded 18:37
PASS 6 forecast at 18:32 det reaches capacity in 10.0 min; ML last_value MAE 1198.75 vs 1198.75 (does not beat baseline)
PASS 7 alternative route Main Stage Arena -> West Concourse -> Food Court | blocked nodes ['exit_east']
PASS 8 virtual heatmap (synthetic) tracks 32, peak 1.12 p/m2
PASS 9 camera/video sample processed yolo + bytetrack (ultralytics), frames 25, unique 5
PASS 10 original + bird's-eye views frame 24 (same frame index for all views)
PASS 11 density heatmap peak density 0.0 p/m2 (calibration: default preset (not calibrated for this camera))
PASS 12 movement vectors dominant W, vectors 2
PASS 12b camera feeds venue assessment main_stage 200 est., others unknown
PASS 13 incident + audit integrity four-eyes blocked=403, sealed root, audit chain valid
```

Theme switching was checked visually, with headless Edge screenshots of the Command Centre, Virtual Heatmap, Overview,
Audit & Verification, Live Monitoring and Analytics in light and dark. The 260 ms transition is a CSS mechanism; static screenshots cannot verify its timing.

## Earlier manual check (pre-integration)

The backend ran in single-server mode (`uvicorn app.main:app --port 8010`, serving `frontend/dist`). Headless Microsoft Edge took screenshots of
Command Centre, Zone Intelligence, Crowd Forecasting, Movement Planner, Analytics and Audit & Verification, and each one rendered backend data.
`/api/crowdguard/status` reported `yolo` (verified), `bytetrack (ultralytics)` and AI `local-fallback`.
The upload → job → results flow on the Live Monitoring screen is covered by the API test above. It was not clicked through in a browser.

## Backend: real-time pipeline tests (`tests/test_crowdguard_live.py`, verbose)

Cameras are replaced by a fake `cv2.VideoCapture` or a fake source in these tests, except `test_yolo_initialises_once_and_detects_people`,
which loads the real local YOLO weights.

```
$ cd backend && python -m pytest -o addopts="" -v tests/test_crowdguard_live.py
tests/test_crowdguard_live.py::test_camera_discovery_reports_available_busy_and_missing PASSED
tests/test_crowdguard_live.py::test_webcam_errors_are_specific PASSED
tests/test_crowdguard_live.py::test_webcam_connects_and_reads PASSED
tests/test_crowdguard_live.py::test_stream_url_validation_hides_credentials PASSED
tests/test_crowdguard_live.py::test_yolo_initialises_once_and_detects_people PASSED
tests/test_crowdguard_live.py::test_ground_projection_round_trip_and_horizon PASSED
tests/test_crowdguard_live.py::test_foot_uncertainty_grows_with_distance PASSED
tests/test_crowdguard_live.py::test_kde_integrates_to_people_count PASSED
tests/test_crowdguard_live.py::test_empty_space_states_and_unknown_when_feed_down PASSED
tests/test_crowdguard_live.py::test_walkable_area_and_restricted_zones_are_blocked PASSED
tests/test_crowdguard_live.py::test_route_avoids_congestion_and_obstacles PASSED
tests/test_crowdguard_live.py::test_unavailable_exit_never_recommended_and_feed_down_gives_no_route PASSED
tests/test_crowdguard_live.py::test_guidance_hysteresis PASSED
tests/test_crowdguard_live.py::test_alert_dedup_escalation_and_cooldown PASSED
tests/test_crowdguard_live.py::test_latest_frame_wins_no_backlog PASSED
tests/test_crowdguard_live.py::test_identity_persists_across_frames PASSED
tests/test_crowdguard_live.py::test_disconnect_marks_area_unknown_and_reconnects PASSED
tests/test_crowdguard_live.py::test_live_api_and_websocket_stream PASSED
tests/test_crowdguard_live.py::test_calibration_api_metric_requires_measurements PASSED
tests/test_crowdguard_live.py::test_default_site_matches_digital_twin PASSED
tests/test_crowdguard_live.py::test_sources_label_recordings_and_simulation_honestly PASSED
tests/test_crowdguard_live.py::test_switching_source_never_serves_the_previous_picture PASSED
tests/test_crowdguard_live.py::test_slow_camera_raises_an_alert PASSED
tests/test_crowdguard_live.py::test_camera_discovery_after_stop_does_not_report_in_use PASSED
============================= 24 passed in 15.70s =============================
```

## Real-time pipeline measurements

Measured through the running server (`uvicorn app.main:app --port 8010`), the REST API and the WebSocket, on a 13th Gen Intel Core
i7-13700HX laptop, CPU inference (no CUDA), with the laptop's webcam. The script started each source, discarded the first 3 s, and then
collected every snapshot. Webcam frames were not viewed (privacy), so detection counts are not accuracy figures. Interpretation:
[`CROWDGUARD_REALTIME_ARCHITECTURE.md`](CROWDGUARD_REALTIME_ARCHITECTURE.md#9-measured-performance).

```
machine: Intel64 Family 6 Model 191 Stepping 2, GenuineIntel | device: cpu | detector: yolo yolov8n.pt
== Webcam: kind=live_camera live=True frame 1280x720
   analysed 12.0 fps (cap 12.0); camera delivers 30.0 fps; frames skipped to stay current 456
   per-frame processing median 26 ms, p95 34 ms; capture->result (server) median 44 ms
   capture->browser-side client median 46 ms, p95 62 ms, max 75 ms (265 snapshots)
   detections/frame median 4 (min 1, max 7); confidence median 0.54
   unique track ids 24; longest-lived (snapshots out of 265): [(1, 245), (14, 98), (23, 98)]
   unit: relative (1.0 = congestion threshold); calibration: assumed (not measured); alerts seen: none
== Recording: kind=recorded_video live=False frame 640x678
   analysed 12.0 fps (cap 12.0); camera delivers 15.2 fps; frames skipped to stay current 44
   per-frame processing median 33 ms, p95 50 ms; capture->result (server) median 70 ms
   capture->browser-side client median 71 ms, p95 101 ms, max 117 ms (145 snapshots)
   detections/frame median 3 (min 2, max 5); confidence median 0.81
   unique track ids 13; longest-lived (snapshots out of 145): [(8, 119), (1, 93), (12, 59)]
   unit: relative (1.0 = congestion threshold); calibration: assumed (not measured); alerts seen: none
== Simulation: kind=synthetic live=False frame 1280x720
   analysed 9.9 fps (cap 12.0); camera delivers 9.9 fps; frames skipped to stay current 0
   per-frame processing median 19 ms, p95 24 ms; capture->result (server) median 20 ms
   capture->browser-side client median 24 ms, p95 34 ms, max 36 ms (120 snapshots)
   detections/frame median 60.0 (min 60, max 60); confidence median 0.92
   unique track ids 60; longest-lived (snapshots out of 120): [(1, 120), (2, 120), (3, 120)]
   unit: persons/m²; calibration: simulated geometry (exact); alerts seen: ['corridor_congestion', 'flow_slowed', 'zone_capacity_exceeded', 'zone_near_capacity']
stop idle
start True
== Webcam uncapped (max_fps 30): analysed median 29.2 fps, min 28.4; per-frame median 29 ms; capture->client median 46 ms p95 61 ms; skipped 17
stop idle
```

Also observed during testing:

* While a second process held the same webcam open, Windows let CROWDGUARD open it too, but it received about 1 frame per second
  (status: `running`, fps 1.0, 32 frames in about 30 s). This is why the `camera_slow` alert exists.
* Camera disconnection was tested with a fake source, not by unplugging a camera.

