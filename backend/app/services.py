"""Composition root: builds the store, engines and registry and wires observers."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.core.contracts import EngineResponse, ExecutionContext
from app.core.registry import EngineRegistry
from app.db.store import Store
from app.engines.ai.engine import AIEngine
from app.engines.crypto.engine import CryptoEngine
from app.engines.crypto.keystore import LocalKeyStore, load_kek
from app.engines.data.engine import DataEngine
from app.engines.decision.engine import DecisionEngine
from app.engines.ml.engine import MLEngine
from app.engines.security.engine import SecurityEngine


@dataclass
class Services:
    settings: Settings
    store: Store
    registry: EngineRegistry


def build_services(settings: Settings) -> Services:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    store = Store(settings.resolved_database_url)

    security = SecurityEngine(store)
    registry = EngineRegistry(authorizer=security.authorizer)
    kek, kek_source = load_kek(settings.master_key, settings.data_dir)
    registry.register(security)
    registry.register(AIEngine(settings, store))
    registry.register(MLEngine(store))
    registry.register(CryptoEngine(LocalKeyStore(store, kek, kek_source), store, kek_source))
    registry.register(DataEngine(store))
    registry.register(DecisionEngine(store))
    registry.add_observer(_recorder(store))
    registry.initialise_all()
    return Services(settings=settings, store=store, registry=registry)


def _recorder(store: Store):
    def observe(engine: str, op: str, payload: dict, ctx: ExecutionContext, resp: EngineResponse, access: str) -> None:
        store.record_execution(
            request_id=ctx.request_id, engine=engine, operation=op, access=access, success=resp.success,
            error_code=resp.error.code if resp.error else None, execution_time_ms=resp.execution_time_ms,
            warnings_count=len(resp.warnings), actor=ctx.actor, role=ctx.role, actor_type=ctx.actor_type, run_id=ctx.run_id)
        if resp.error and resp.error.code == "FORBIDDEN":
            store.audit("security", "access_denied", actor=ctx.actor, role=ctx.role, severity="warning",
                        detail={"engine": engine, "operation": op, "actor_type": ctx.actor_type, "reason": resp.error.message})
        elif access != "read" and resp.success:
            store.audit("engine", f"{engine}.{op}", actor=ctx.actor, role=ctx.role,
                        detail={"request_id": ctx.request_id, "run_id": ctx.run_id, "access": access})
    return observe
