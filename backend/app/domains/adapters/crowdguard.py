"""CrowdGuard: Virtual Bird's-Eye Crowd Intelligence domain adapter."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, table, narrative_of


class ZoneInput(BaseModel):
    id: str
    name: str
    capacity: int
    area_sq_meters: float
    observed_people: int
    avg_speed_mps: float


class CrowdGuardInput(BaseModel):
    venue_name: str = Field("Grand Concourse & Stadium Plaza", min_length=2)
    camera_id: str = Field("CAM-NORTH-04", min_length=2)
    zones: List[ZoneInput] = Field(..., min_length=2)
    sampling_fps: float = Field(25.0, ge=1.0)


RULES = [
    {
        "id": "critical-density-crush",
        "description": "Density exceeds Fruin Level-of-Service F (>3.0 p/m²)",
        "severity": "critical",
        "outcome": "halt_ingress_divert_crowd",
        "when": {"field": "density_per_sq_meter", "op": "gte", "value": 3.0},
    },
    {
        "id": "bottleneck-stagnation",
        "description": "High density combined with severe velocity stagnation (<0.35 m/s)",
        "severity": "high",
        "outcome": "clear_bottleneck_corridor",
        "when": {"field": "is_bottleneck", "op": "eq", "value": True},
    },
    {
        "id": "moderate-flow",
        "description": "Normal active movement throughout venue",
        "severity": "low",
        "outcome": "maintain_standard_monitoring",
        "when": {"field": "density_per_sq_meter", "op": "lt", "value": 1.5},
    },
]


def _facts(pc: PipelineContext) -> dict:
    facts = []
    for z in pc.input["zones"]:
        density = z["observed_people"] / max(1.0, z["area_sq_meters"])
        is_bneck = density >= 1.5 and z["avg_speed_mps"] < 0.35
        facts.append({
            "zone_id": z["id"],
            "density_per_sq_meter": density,
            "is_bottleneck": is_bneck,
            "occupancy_pct": (z["observed_people"] / max(1, z["capacity"])) * 100.0,
        })
    return {"rules": RULES, "facts": facts, "default_outcome": "maintain_standard_monitoring"}


def _risk(pc: PipelineContext) -> dict:
    items = []
    for z in pc.input["zones"]:
        density = z["observed_people"] / max(1.0, z["area_sq_meters"])
        occ_ratio = min(2.0, z["observed_people"] / max(1, z["capacity"]))
        speed_factor = max(0.0, 1.5 - min(1.5, z["avg_speed_mps"])) / 1.5

        items.append({
            "id": z["id"],
            "factors": [
                {"name": "Crowd Density (p/m²)", "value": min(4.0, density), "max": 4.0, "weight": 4},
                {"name": "Capacity Overfill", "value": occ_ratio, "max": 1.5, "weight": 3},
                {"name": "Velocity Stagnation", "value": speed_factor, "max": 1.0, "weight": 2},
            ],
        })
    return {"items": items, "thresholds": {"medium": 35, "high": 60, "critical": 80}}


def present(pc: PipelineContext) -> dict:
    zones = pc.input["zones"]
    rules_res = pc.r("rules")["results"]
    risk_res = pc.r("risk")["items"]

    total_people = sum(z["observed_people"] for z in zones)
    total_area = sum(z["area_sq_meters"] for z in zones)
    overall_density = total_people / max(1.0, total_area)

    rows = []
    critical_count = 0
    for z, r, pr in zip(zones, rules_res, risk_res):
        density = z["observed_people"] / max(1.0, z["area_sq_meters"])
        if r["max_severity"] == "critical" or pr["band"] == "critical":
            critical_count += 1
        rows.append({
            "zone": z["name"],
            "population": f"{z['observed_people']} / {z['capacity']}",
            "density": f"{density:.2f} p/m²",
            "avg_speed": f"{z['avg_speed_mps']:.2f} m/s",
            "risk_score": pr["score"],
            "band": pr["band"],
            "action": r["outcome"],
        })
    rows.sort(key=lambda x: -x["risk_score"])

    return {
        "headline": f"{total_people} persons monitored across {len(zones)} zones · {critical_count} zone(s) at critical congestion risk",
        "metrics": [
            metric("Total Crowd Population", total_people, "bad" if critical_count > 0 else "good"),
            metric("Mean Venue Density", f"{overall_density:.2f} p/m²", "warn" if overall_density > 1.5 else "good"),
            metric("Critical Zones", critical_count, "bad" if critical_count > 0 else "good"),
            metric("Monitored Venue Area", f"{total_area:.0f} m²", "neutral"),
        ],
        "charts": [
            chart("bar", "Population & Capacity by Monitored Zone", [
                {"zone": z["name"], "people": z["observed_people"], "capacity": z["capacity"]}
                for z in zones
            ], "zone", [("people", "Current Population"), ("capacity", "Safe Capacity")]),
        ],
        "tables": [
            table("Crowd Safety & Ingress Queue Triage", [
                ("zone", "Zone"), ("population", "Population / Cap"), ("density", "Density"),
                ("avg_speed", "Avg Speed"), ("risk_score", "Risk Index"), ("band", "Risk Band"),
                ("action", "Egress Directive"),
            ], rows)
        ],
        "narrative": narrative_of(pc, "summary", "summary"),
        "notes": [
            "Projective 2D planar homography transforms camera perspectives into physical metric coordinates.",
            "Density thresholds follow Fruin Level-of-Service standards (>3.0 p/m² triggers mandatory ingress halt).",
        ],
    }


ADAPTER = DomainAdapter(
    id="crowdguard",
    name="CROWDGUARD Virtual Crowd Intelligence",
    icon="Eye",
    color="#06b6d4",
    tagline="Transform camera footage into a virtual bird's-eye crowd density and movement map",
    description="Transforms oblique CCTV video into a calibrated top-down bird's-eye spatial representation, calculates continuous Gaussian crowd density (persons/m²), tracks movement vectors, and alerts operators to bottlenecks and crush risks.",
    scenario="Virtual Bird's-Eye Crowd Intelligence & Risk Mitigation",
    impact="Provides event commanders with real-time top-down spatial visibility of accumulation, counterflow, and egress constrictions.",
    input_model=CrowdGuardInput,
    sample_file="crowdguard.json",
    present=present,
    sections=["virtual-heatmap", "overview", "workspace", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("rules", "Crowd Density Safety Rules", "decision", "evaluate_rules", build=_facts, why="Deterministic safety overrides based on physical crowd density"),
        Step("risk", "Zone Risk Assessment", "decision", "risk_score", build=_risk, why="Multi-factor spatial risk synthesis"),
        Step("summary", "Commander Situation Report", "ai", "summarize", optional=True,
             build=lambda pc: {
                 "text": f"Monitored venue: {pc.input['venue_name']}. Total crowd {sum(z['observed_people'] for z in pc.input['zones'])} across {len(pc.input['zones'])} zones. Highest risk zone has density {max(z['observed_people']/z['area_sq_meters'] for z in pc.input['zones']):.2f} p/m².",
                 "max_sentences": 2,
             }),
    ],
)
