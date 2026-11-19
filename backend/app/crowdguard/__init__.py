"""CROWDGUARD: crowd safety monitoring services and the Virtual Crowd Intelligence Engine (VCIE).

One analysis chain, one implementation per stage:

  camera / video / simulation
    -> calibration.py        four-point homography (camera <-> bird's-eye ground plane)
    -> crowd_detection.py    the only person detector (local YOLO, labelled OpenCV-HOG fallback)
       detection.py          projects detections onto the calibrated ground plane
    -> crowd_tracking.py     image-space identity (ByteTrack, IoU fallback)
       tracking.py           ground-plane Kalman kinematics (position, velocity, m/s)
    -> density.py            Gaussian KDE density map + bird's-eye zone metrics
       density_estimator.py  zone occupancy estimate with uncertainty, bands, data quality
    -> zone_manager.py       polygon zones and counting
    -> crowd_flow.py / movement.py   flow statistics and movement vectors
    -> congestion_detector.py rule-based alerts (decision engine)
    -> crowd_forecaster.py   short-horizon forecasting (+ ml engine)
    -> route_optimizer.py    safety-weighted routing (NetworkX)
    -> safety_recommendations.py advisory actions for human organisers
  pipeline.py / media_analysis.py orchestrate the vision chain; simulation.py / synthetic.py are the
  deterministic synthetic sources (always labelled synthetic).

Safety position (applies to every module):
  * Counts are estimates, never ground truth. Occlusion and tracking errors are modelled explicitly.
  * A missing or stale feed is *unknown*, never zero.
  * Outputs are advisory. Human organisers make every intervention decision.
  * No software recommendation may close or restrict an emergency exit.
"""
