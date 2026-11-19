"""Persistence facade. Engines and routes depend on this, never on raw sessions."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Integer, cast, create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Approval,
    AuditEvent,
    Base,
    CrowdIncident,
    Dataset,
    Document,
    ExecutionRecord,
    KeyRecord,
    PipelineRun,
    RagChunk,
    Setting,
    utcnow_iso,
)

GENESIS_HASH = "0" * 64


def new_id() -> str:
    return uuid.uuid4().hex


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _row(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


class Store:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///"):
            Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, future=True)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._audit_lock = threading.Lock()
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    def ping(self) -> bool:
        with self.session() as s:
            s.execute(select(1))
        return True

    # ---- settings --------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.session() as s:
            row = s.get(Setting, key)
            return row.value if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.session() as s:
            row = s.get(Setting, key)
            if row:
                row.value = value
            else:
                s.add(Setting(key=key, value=value))

    # ---- audit (hash chained) ------------------------------------------
    @staticmethod
    def _audit_digest(prev_hash: str, body: dict[str, Any]) -> str:
        return hashlib.sha256((prev_hash + canonical_json(body)).encode("utf-8")).hexdigest()

    def audit(self, category: str, action: str, *, actor: str = "system", role: str = "system",
              severity: str = "info", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {
            "ts": utcnow_iso(), "category": category, "action": action, "actor": actor,
            "role": role, "severity": severity, "detail": json.loads(canonical_json(detail or {})),
        }
        with self._audit_lock, self.session() as s:
            last = s.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).scalar_one_or_none()
            prev_hash = last.hash if last else GENESIS_HASH
            event = AuditEvent(**body, prev_hash=prev_hash, hash=self._audit_digest(prev_hash, body))
            s.add(event)
            s.flush()
            return _row(event)

    def list_audit(self, limit: int = 100, category: str | None = None) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
            if category:
                q = q.where(AuditEvent.category == category)
            return [_row(e) for e in s.execute(q).scalars()]

    def verify_audit_chain(self) -> dict[str, Any]:
        prev = GENESIS_HASH
        checked = 0
        with self.session() as s:
            for e in s.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars():
                body = {k: getattr(e, k) for k in ("ts", "category", "action", "actor", "role", "severity", "detail")}
                expected = self._audit_digest(prev, body)
                if e.prev_hash != prev or e.hash != expected:
                    return {"valid": False, "checked": checked, "broken_at_id": e.id,
                            "reason": "prev_hash mismatch" if e.prev_hash != prev else "content hash mismatch"}
                prev = e.hash
                checked += 1
        return {"valid": True, "checked": checked, "head": prev}

    # ---- executions -----------------------------------------------------
    def record_execution(self, **fields: Any) -> None:
        with self.session() as s:
            s.add(ExecutionRecord(**fields))

    def list_executions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(ExecutionRecord).order_by(ExecutionRecord.id.desc()).limit(limit)
            return [_row(e) for e in s.execute(q).scalars()]

    def execution_stats(self) -> dict[str, Any]:
        with self.session() as s:
            per_engine = s.execute(
                select(
                    ExecutionRecord.engine,
                    func.count(),
                    func.sum(cast(ExecutionRecord.success, Integer)),
                    func.avg(ExecutionRecord.execution_time_ms),
                    func.max(ExecutionRecord.execution_time_ms),
                ).group_by(ExecutionRecord.engine)
            ).all()
            per_op = s.execute(
                select(ExecutionRecord.engine, ExecutionRecord.operation, func.count(),
                       func.avg(ExecutionRecord.execution_time_ms))
                .group_by(ExecutionRecord.engine, ExecutionRecord.operation)
                .order_by(func.count().desc()).limit(15)
            ).all()
            errors = s.execute(
                select(ExecutionRecord.error_code, func.count())
                .where(ExecutionRecord.success.is_(False)).group_by(ExecutionRecord.error_code)
            ).all()
            runs = s.execute(
                select(PipelineRun.domain, PipelineRun.status, func.count(), func.avg(PipelineRun.duration_ms))
                .group_by(PipelineRun.domain, PipelineRun.status)
            ).all()
        return {
            "per_engine": [
                {"engine": e, "count": c, "success": int(ok or 0), "avg_ms": round(avg or 0, 2), "max_ms": round(mx or 0, 2)}
                for e, c, ok, avg, mx in per_engine
            ],
            "per_operation": [
                {"engine": e, "operation": o, "count": c, "avg_ms": round(avg or 0, 2)} for e, o, c, avg in per_op
            ],
            "errors": [{"code": code or "UNKNOWN", "count": c} for code, c in errors],
            "runs": [
                {"domain": d, "status": st, "count": c, "avg_ms": round(avg or 0, 2)} for d, st, c, avg in runs
            ],
        }

    # ---- pipeline runs --------------------------------------------------
    def save_run(self, run: dict[str, Any]) -> None:
        with self.session() as s:
            s.merge(PipelineRun(**run))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(PipelineRun, run_id)
            return _row(row) if row else None

    def list_runs(self, limit: int = 50, domain: str | None = None) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
            if domain:
                q = q.where(PipelineRun.domain == domain)
            rows = s.execute(q).scalars().all()
            out = []
            for r in rows:
                d = _row(r, exclude={"input", "presentation"})
                d["steps"] = [{k: st.get(k) for k in ("id", "title", "status", "execution_time_ms")} for st in (r.steps or [])]
                d["headline"] = (r.presentation or {}).get("headline")
                out.append(d)
            return out

    # ---- documents ------------------------------------------------------
    def add_document(self, **fields: Any) -> dict[str, Any]:
        with self.session() as s:
            doc = Document(id=new_id(), **fields)
            s.add(doc)
            s.flush()
            return _row(doc)

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(Document, doc_id)
            return _row(row) if row else None

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(Document).order_by(Document.created_at.desc()).limit(limit)
            return [_row(d) for d in s.execute(q).scalars()]

    # ---- datasets -------------------------------------------------------
    def add_dataset(self, **fields: Any) -> dict[str, Any]:
        with self.session() as s:
            ds = Dataset(id=new_id(), **fields)
            s.add(ds)
            s.flush()
            return _row(ds, exclude={"records"})

    def get_dataset(self, ds_id: str, with_records: bool = True) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(Dataset, ds_id)
            if not row:
                return None
            return _row(row, exclude=None if with_records else {"records"})

    def list_datasets(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(Dataset).order_by(Dataset.created_at.desc()).limit(limit)
            return [_row(d, exclude={"records"}) for d in s.execute(q).scalars()]

    # ---- keys -----------------------------------------------------------
    def add_key(self, **fields: Any) -> dict[str, Any]:
        with self.session() as s:
            key = KeyRecord(id=new_id(), **fields)
            s.add(key)
            s.flush()
            return _row(key)

    def get_key(self, key_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(KeyRecord, key_id)
            return _row(row) if row else None

    def find_key_by_label(self, label: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.execute(
                select(KeyRecord).where(KeyRecord.label == label).order_by(KeyRecord.created_at.desc()).limit(1)
            ).scalar_one_or_none()
            return _row(row) if row else None

    def list_keys(self) -> list[dict[str, Any]]:
        with self.session() as s:
            return [_row(k, exclude={"wrapped_material"}) for k in s.execute(select(KeyRecord)).scalars()]

    # ---- approvals ------------------------------------------------------
    def add_approval(self, **fields: Any) -> dict[str, Any]:
        with self.session() as s:
            row = Approval(id=new_id(), **fields)
            s.add(row)
            s.flush()
            return _row(row)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(Approval, approval_id)
            return _row(row) if row else None

    def update_approval(self, approval_id: str, **fields: Any) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(Approval, approval_id)
            if not row:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            s.flush()
            return _row(row)

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
            if status:
                q = q.where(Approval.status == status)
            return [_row(a) for a in s.execute(q).scalars()]

    # ---- RAG chunks -----------------------------------------------------
    def replace_chunks(self, collection: str, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        with self.session() as s:
            s.execute(delete(RagChunk).where(RagChunk.collection == collection, RagChunk.doc_id == doc_id))
            for i, ch in enumerate(chunks):
                s.add(RagChunk(collection=collection, doc_id=doc_id, chunk_index=i, text=ch["text"], meta=ch.get("meta", {})))

    def list_chunks(self, collection: str) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(RagChunk).where(RagChunk.collection == collection).order_by(RagChunk.doc_id, RagChunk.chunk_index)
            return [_row(c) for c in s.execute(q).scalars()]

    def list_collections(self) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(RagChunk.collection, func.count(), func.count(func.distinct(RagChunk.doc_id))).group_by(RagChunk.collection)
            ).all()
            return [{"collection": c, "chunks": n, "documents": d} for c, n, d in rows]

    # ---- crowd incidents (CROWDGUARD) -----------------------------------
    def add_incident(self, **fields: Any) -> dict[str, Any]:
        with self.session() as s:
            row = CrowdIncident(**fields)
            s.add(row)
            s.flush()
            return _row(row)

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(CrowdIncident, incident_id)
            return _row(row) if row else None

    def update_incident(self, incident_id: str, **fields: Any) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(CrowdIncident, incident_id)
            if not row:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            s.flush()
            return _row(row)

    def list_incidents(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(CrowdIncident).order_by(CrowdIncident.created_at.desc()).limit(limit)
            if status:
                q = q.where(CrowdIncident.status == status)
            return [_row(r) for r in s.execute(q).scalars()]

    # ---- overview -------------------------------------------------------
    def counts(self) -> dict[str, int]:
        with self.session() as s:
            def count(model, *where):
                q = select(func.count()).select_from(model)
                for w in where:
                    q = q.where(w)
                return s.execute(q).scalar_one()

            return {
                "executions": count(ExecutionRecord),
                "failed_executions": count(ExecutionRecord, ExecutionRecord.success.is_(False)),
                "pipeline_runs": count(PipelineRun),
                "documents": count(Document),
                "datasets": count(Dataset),
                "keys": count(KeyRecord),
                "audit_events": count(AuditEvent),
                "pending_approvals": count(Approval, Approval.status == "pending"),
                "security_events": count(AuditEvent, AuditEvent.category == "security"),
                "crowd_incidents": count(CrowdIncident),
                "open_crowd_incidents": count(CrowdIncident, CrowdIncident.status.not_in(["resolved", "closed"])),
            }

