# CROWDGUARD — two-minute pitch

**(0:00) The problem.** Crowd crushes rarely come out of nowhere. Minutes before they happen, a zone fills faster than it empties, a corridor
saturates, or an exit gets blocked. Organisers usually find out from a radio call after the fact. They need to see the build-up early and
know where people can safely go instead.

**(0:20) What CROWDGUARD does.** It turns camera footage into per-zone occupancy estimates, flags overcrowding and fast build-up,
forecasts a capacity breach about ten minutes ahead, and recommends where to move people, explaining why for each recommendation.

**(0:35) Live demo.** This is a deterministic synthetic festival, labelled as synthetic on every screen. At 18:20 the Main Stage is only
half full, but it is filling at more than two percent of capacity per minute, so CROWDGUARD raises an early warning. At 18:32 the forecast shows
a breach about ten minutes ahead, and the planner proposes a relief route. Note that it moves people to the Second Stage and the Food Court, never
into another crowded zone, and it checks destination capacity against the *upper* estimate. At 18:40 the organisers approve. The peak stops at about
105 %. In the same scenario without that decision, the Main Stage reaches about 158 %. Then an emergency exit gets blocked: the system raises a critical
alert, sends stewards to clear it, and re-plans egress to the other exits. A camera drops out, and the Food Court shows as *unknown*, not empty,
so the planner stops sending people there until someone checks.

**(1:15) Real computer vision.** On the Live Monitoring screen, YOLO detects people in an uploaded video. ByteTrack follows each person across frames
so nobody is counted twice. Each person's foot point places them in a polygon zone, and the tracks give direction and speed. We show three numbers
side by side: what the detector saw, the occlusion-corrected estimate with its interval, and the number of unique people.

**(1:35) Why it can be trusted.** First, every number is labelled as observed, estimate or synthetic, and missing data is never treated as zero.
Second, the AI only advises. Alert rules are deterministic, a human makes every decision, closing an incident needs a second person, and no software
action can close an emergency exit. Third, every incident is hash-chained and sealed under a Merkle root, so tampering is detected.
It runs on the OMNIFORGE engines: the decision engine evaluates the rules, the ML engine runs backtested forecasting, the AI engine writes briefings with Gemini or a local fallback, and the crypto engine handles evidence.

**(1:55) Close.** CROWDGUARD gives organisers minutes of warning and a vetted route instead of a guess. The decision stays with them.
