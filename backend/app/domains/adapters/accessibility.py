"""Social impact & accessibility: plain-language rewriting with measured readability."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, table


class Input(BaseModel):
    title: str = Field("", max_length=300)
    text: str = Field(..., min_length=40, max_length=100_000)
    target_grade: int = Field(8, ge=3, le=14)


def present(pc: PipelineContext) -> dict:
    s = pc.r("simplify")
    b, a = s["before"], s["after"]
    meta = pc.meta.get("simplify") or {}
    key = pc.r("key_points")
    rows = [{"measure": "Flesch-Kincaid grade", "before": b["flesch_kincaid_grade"], "after": a["flesch_kincaid_grade"]},
            {"measure": "Flesch reading ease (higher = easier)", "before": b["flesch_reading_ease"], "after": a["flesch_reading_ease"]},
            {"measure": "Words per sentence", "before": b["avg_words_per_sentence"], "after": a["avg_words_per_sentence"]},
            {"measure": "Complex words (3+ syllables) %", "before": round(b["complex_word_ratio"] * 100, 1), "after": round(a["complex_word_ratio"] * 100, 1)},
            {"measure": "Sentences over 25 words", "before": b["long_sentences"], "after": a["long_sentences"]}]
    text = s["simplified"]
    if key and key.get("summary"):
        text += "\n\nKey points: " + key["summary"]
    return {
        "headline": f"Reading grade {b['flesch_kincaid_grade']} → {a['flesch_kincaid_grade']} (target ≤ {pc.input['target_grade']}: "
                    f"{'met' if s['meets_target'] else 'not yet met'})",
        "metrics": [
            metric("Grade before", b["flesch_kincaid_grade"], "bad" if b["flesch_kincaid_grade"] > pc.input["target_grade"] else "good"),
            metric("Grade after", a["flesch_kincaid_grade"], "good" if s["meets_target"] else "warn"),
            metric("Grade reduction", s["grade_reduction"], "good" if s["grade_reduction"] > 0 else "warn"),
            metric("Rewrite method", "LLM" if not meta.get("fallback") else "local rules",
                   hint=meta.get("model") or meta.get("fallback_reason")),
        ],
        "charts": [chart("bar", "Readability before vs after", rows[:3] + rows[4:], "measure", [("before", "Before"), ("after", "After")])],
        "tables": [table("Readability measures", [("measure", "Measure"), ("before", "Before"), ("after", "After")], rows),
                   table("Changes applied", [("change", "Change")], [{"change": c} for c in s["changes"]] or [{"change": "LLM rewrite (see text)"}])],
        "narrative": {"text": text, "source": meta.get("provider", "unknown"), "model": meta.get("model"), "fallback": bool(meta.get("fallback"))},
        "notes": ["Readability is measured with standard Flesch formulas on both versions; the improvement is computed, not claimed.",
                  "Always have a person check that rewritten public notices keep every obligation, date and number."],
    }


ADAPTER = DomainAdapter(
    id="accessibility", name="Social Impact & Accessibility", icon="Accessibility", color="#0d9488",
    tagline="Turn bureaucratic notices into plain language and prove the readability gain",
    description="Measures readability of the original text, rewrites it in plain language (LLM, or a transparent local rule set), re-measures, and extracts key points so people with low literacy or cognitive impairments can act on official information.",
    scenario="Plain-language public notices", impact="Measurably easier notices: grade level and sentence length before vs after.",
    input_model=Input, sample_file="accessibility.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "engines", "audit", "settings"],
    steps=[
        Step("baseline", "Measure original", "data", "text_features", build=lambda pc: {"text": pc.input["text"]},
             why="Flesch reading ease and grade level"),
        Step("simplify", "Plain-language rewrite", "ai", "simplify",
             build=lambda pc: {"text": pc.input["text"], "target_grade": pc.input["target_grade"]}, why="Rewrite + before/after measurement"),
        Step("key_points", "Key points", "ai", "summarize", optional=True,
             build=lambda pc: {"text": pc.r("simplify")["simplified"], "max_sentences": 3}),
    ],
)
