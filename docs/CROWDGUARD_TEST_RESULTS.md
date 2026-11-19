# CROWDGUARD — automated test results

Recorded on the build machine on 2026-11-19 (Windows 11, Python 3.12.0, Node v26.7.0). These are copied from actual runs
on branch `integration/omniforge-final` (OMNIFORGE + frontend + CROWDGUARD + VCIE); nothing was edited by hand. Re-run them with the commands shown.

## Backend: full suite

```
$ cd backend && python -m pytest -o addopts="" -q
121 passed

tests/test_ai.py               10 passed
tests/test_api.py              25 passed   (incl. the parametrised pipeline test for all 10 adapters)
tests/test_crowdguard.py       23 passed
tests/test_crowdguard_vcie.py  19 passed   (12 VCIE tests + 7 integration tests)
tests/test_crypto.py           18 passed
tests/test_decision.py          5 passed
tests/test_ml_data.py          13 passed
tests/test_security.py          8 passed
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
