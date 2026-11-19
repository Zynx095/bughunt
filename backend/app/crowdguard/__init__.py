"""CROWDGUARD: crowd safety monitoring services.

Each module is a plain, independently testable service. The `crowd` engine
(app/engines/crowd) exposes them as typed operations through the OMNIFORGE
registry, so policy, validation, audit and the response envelope apply.

Safety position (applies to every module):
  * Counts are estimates, never ground truth. Occlusion and tracking errors are modelled explicitly.
  * A missing or stale feed is *unknown*, never zero.
  * Outputs are advisory. Human organisers make every intervention decision.
  * No software recommendation may close or restrict an emergency exit.
"""
