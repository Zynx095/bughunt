"""Education & academia: grounded course Q&A and learner support grouping."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import DomainAdapter, PipelineContext, Step, chart, metric, table

FEATURES = ["quiz_avg", "assignment_avg", "attendance_pct", "forum_posts", "late_submissions"]


class Document(BaseModel):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    title: str
    text: str = Field(..., min_length=20)


class Student(BaseModel):
    student_id: str
    quiz_avg: float = Field(..., ge=0, le=100)
    assignment_avg: float = Field(..., ge=0, le=100)
    attendance_pct: float = Field(..., ge=0, le=100)
    forum_posts: int = Field(..., ge=0)
    late_submissions: int = Field(..., ge=0)


class Input(BaseModel):
    course: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,48}$")
    question: str = Field(..., min_length=3)
    documents: list[Document] = Field(..., min_length=1, max_length=500)
    students: list[Student] = Field(..., min_length=6, max_length=50_000)


def _profiles(pc: PipelineContext) -> list[dict]:
    clusters = pc.r("clusters")["clusters"]
    ranked = sorted(clusters, key=lambda c: c["centroid"]["quiz_avg"] + c["centroid"]["attendance_pct"])
    names = {ranked[0]["cluster"]: "needs support"} if len(ranked) > 1 else {}
    if len(ranked) > 1:
        names[ranked[-1]["cluster"]] = "thriving"
    rows = []
    for c in clusters:
        rows.append({"group": f"G{c['cluster'] + 1}", "label": names.get(c["cluster"], "steady"), "students": c["size"],
                     **{k: round(c["centroid"][k], 1) for k in FEATURES}})
    return sorted(rows, key=lambda r: r["quiz_avg"])


def present(pc: PipelineContext) -> dict:
    ans, cl = pc.r("answer"), pc.r("clusters")
    profiles = _profiles(pc)
    support = next((p for p in profiles if p["label"] == "needs support"), None)
    meta = pc.meta.get("answer") or {}
    summaries = [{"document": d["title"], "summary": s["summary"] if s else "—"}
                 for d, s in zip(pc.input["documents"], pc.r("summaries"))]
    proj = [{"x": p["x"], "y": p["y"], "group": f"G{p['cluster'] + 1}"} for p in cl["projection"]]
    return {
        "headline": f"Answered from {len(ans['citations'])} cited passage(s); {support['students'] if support else 0} learners grouped for targeted support",
        "metrics": [
            metric("Retrieval top score", ans.get("top_score", 0), hint="TF-IDF cosine similarity of best passage"),
            metric("Learner groups", cl["k"], hint=f"silhouette {cl['silhouette']}"),
            metric("Needs support", support["students"] if support else 0, "warn" if support else "good"),
            metric("Documents indexed", len(pc.input["documents"])),
        ],
        "charts": [chart("scatter", "Learner groups (PCA projection of engagement features)", proj, "x", [("y", "")], color_key="group")],
        "tables": [table("Learner group profiles (cluster means)", [("group", "Group"), ("label", "Label"), ("students", "Students"),
                         ("quiz_avg", "Quiz avg"), ("assignment_avg", "Assignment avg"), ("attendance_pct", "Attendance %"),
                         ("forum_posts", "Forum posts"), ("late_submissions", "Late")], profiles),
                   table("Document summaries", [("document", "Document"), ("summary", "Summary")], summaries)],
        "narrative": {"text": f"Q: {pc.input['question']}\n\nA: {ans['answer'] or 'Not found in course materials.'}",
                      "source": meta.get("provider", "unknown"), "model": meta.get("model"), "fallback": bool(meta.get("fallback"))},
        "notes": ["Answers cite the passages they come from; passages flagged for prompt injection are excluded.",
                  "Groups are descriptive clusters to target support, not grades or predictions. Student data is synthetic."],
    }


ADAPTER = DomainAdapter(
    id="education", name="Education & Academia", icon="GraduationCap", color="#d97706",
    tagline="Grounded answers from course material, plus learner groups for targeted support",
    description="Indexes course documents for retrieval, answers student questions with citations (LLM or extractive fallback), summarises each document, and clusters learners by engagement so tutors can target support.",
    scenario="Course assistant & learner support", impact="Students get cited answers instantly; tutors see who needs help.",
    input_model=Input, sample_file="education.json", present=present,
    sections=["overview", "workspace", "ingestion", "runs", "analytics", "engines", "audit", "settings"],
    steps=[
        Step("index", "Index course material", "ai", "rag_index",
             build=lambda pc: {"collection": f"edu-{pc.input['course']}", "documents": pc.input["documents"]}, why="Chunk + TF-IDF index"),
        Step("answer", "Answer with citations", "ai", "rag_query",
             build=lambda pc: {"collection": f"edu-{pc.input['course']}", "question": pc.input["question"]}, why="Retrieval-augmented, cited answer"),
        Step("summaries", "Summarise documents", "ai", "summarize", foreach=True, optional=True,
             build=lambda pc: [{"text": d["text"], "max_sentences": 2} for d in pc.input["documents"]]),
        Step("clusters", "Group learners", "ml", "cluster",
             build=lambda pc: {"records": pc.input["students"], "features": FEATURES}, why="K-means with silhouette-selected k"),
    ],
)
