# CROWDGUARD — automated test results

Recorded on the build machine on 2026-11-19 (Windows 11, Python 3.12.0, Node v26.7.0). These are copied from actual runs
on branch `feature/crowdguard-solution`; nothing was edited by hand. Re-run them with the commands shown.

## Backend: full suite

```
$ cd backend && python -m pytest -o addopts="" -q
102 passed
```

This covers the 78 original OMNIFORGE tests, the parametrised pipeline test (which now includes the `crowd_safety` adapter), and 23 CROWDGUARD tests.
One existing assertion changed: `test_health_and_engines` now expects the seven engines (the original six plus `crowd`).

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

## Frontend

```
$ cd frontend && npm run build      # tsc -b && vite build  → ✓ built (exit 0)
$ cd frontend && npm run lint       # oxlint → 0 warnings, 0 errors
```

## Manual end-to-end check

The backend ran in single-server mode (`uvicorn app.main:app --port 8010`, serving `frontend/dist`). Headless Microsoft Edge took screenshots of
Command Centre, Zone Intelligence, Crowd Forecasting, Movement Planner, Analytics and Audit & Verification, and each one rendered backend data.
`/api/crowdguard/status` reported `yolo` (verified), `bytetrack (ultralytics)` and AI `local-fallback`.
The upload → job → results flow on the Live Monitoring screen is covered by the API test above. It was not clicked through in a browser.
