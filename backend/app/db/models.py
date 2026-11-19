"""SQLAlchemy ORM models (SQLite by default)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Base(DeclarativeBase):
    pass


class ExecutionRecord(Base):
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    engine: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    access: Mapped[str] = mapped_column(String(16), default="read")
    success: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    actor: Mapped[str] = mapped_column(String(128), default="anonymous")
    role: Mapped[str] = mapped_column(String(32), default="analyst")
    actor_type: Mapped[str] = mapped_column(String(16), default="human")
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso, index=True)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    domain: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(128), default="anonymous")
    role: Mapped[str] = mapped_column(String(32), default="analyst")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    presentation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso, index=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AuditEvent(Base):
    """Append-only, hash-chained audit log (tamper-evident, not tamper-proof)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    uploaded_by: Mapped[str] = mapped_column(String(128), default="anonymous")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    records: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)


class KeyRecord(Base):
    __tablename__ = "keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), index=True)
    key_type: Mapped[str] = mapped_column(String(16))
    public_key_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    wrapped_material: Mapped[str] = mapped_column(Text)  # AES-GCM(KEK) of the secret key bytes
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(128))
    requested_role: Mapped[str] = mapped_column(String(32))
    requested_actor_type: Mapped[str] = mapped_column(String(16), default="human")
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection: Mapped[str] = mapped_column(String(64), index=True)
    doc_id: Mapped[str] = mapped_column(String(128))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
