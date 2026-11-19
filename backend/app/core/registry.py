"""Engine registry: the single place engines are wired together.

The registry owns:
  * engine lookup by name (no engine imports another engine directly),
  * deterministic authorisation before every operation (fail-closed),
  * observer notification (persistence/audit) after every operation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from .contracts import EngineErrorInfo, EngineResponse, ExecutionContext
from .engine import BaseEngine

log = logging.getLogger("omniforge.registry")


class Authorizer(Protocol):
    def __call__(self, ctx: ExecutionContext, permission: str, access: str) -> tuple[bool, str]: ...


Observer = Callable[[str, str, dict[str, Any], ExecutionContext, EngineResponse, str], None]


def _fail_closed(ctx: ExecutionContext, permission: str, access: str) -> tuple[bool, str]:
    if access == "read":
        return True, "no authorizer configured; read access allowed"
    return False, "no authorizer configured; non-read access denied (fail-closed)"


class EngineRegistry:
    def __init__(self, authorizer: Authorizer | None = None) -> None:
        self._engines: dict[str, BaseEngine] = {}
        self._observers: list[Observer] = []
        self.authorizer: Authorizer = authorizer or _fail_closed

    # ---- composition ---------------------------------------------------
    def register(self, engine: BaseEngine) -> BaseEngine:
        if engine.name in self._engines:
            raise ValueError(f"Engine '{engine.name}' already registered")
        self._engines[engine.name] = engine
        return engine

    def add_observer(self, observer: Observer) -> None:
        self._observers.append(observer)

    def initialise_all(self) -> None:
        for engine in self._engines.values():
            try:
                engine.initialise(self)
            except Exception:  # noqa: BLE001 - one bad engine must not take the app down
                log.exception("Engine '%s' failed to initialise", engine.name)

    # ---- lookup --------------------------------------------------------
    def get(self, name: str) -> BaseEngine | None:
        return self._engines.get(name)

    def names(self) -> list[str]:
        return list(self._engines)

    def describe(self) -> list[dict[str, Any]]:
        return [e.describe() for e in self._engines.values()]

    def health(self) -> dict[str, Any]:
        out = {}
        for name, engine in self._engines.items():
            try:
                out[name] = engine.health()
            except Exception as exc:  # noqa: BLE001
                out[name] = {"status": "error", "detail": str(exc)}
        return out

    # ---- execution -----------------------------------------------------
    def execute(self, engine_name: str, op_name: str, payload: dict[str, Any], ctx: ExecutionContext) -> EngineResponse:
        engine = self._engines.get(engine_name)
        if engine is None:
            resp = EngineResponse(
                success=False,
                engine=engine_name,
                metadata={"operation": op_name, "request_id": ctx.request_id},
                error=EngineErrorInfo(code="UNKNOWN_ENGINE", message=f"No engine named '{engine_name}'",
                                      details={"available": self.names()}),
            )
            resp._status = 404
            return resp

        op = engine.operations.get(op_name)
        if op is not None:
            allowed, reason = self.authorizer(ctx, op.permission, op.access)
            if not allowed:
                resp = EngineResponse(
                    success=False,
                    engine=engine_name,
                    metadata={"operation": op_name, "request_id": ctx.request_id,
                              "permission": op.permission, "role": ctx.role, "actor_type": ctx.actor_type},
                    error=EngineErrorInfo(code="FORBIDDEN", message=reason),
                )
                resp._status = 403
                self._notify(engine_name, op_name, payload, ctx, resp, op.access)
                return resp

        resp = engine.execute(op_name, payload, ctx)
        self._notify(engine_name, op_name, payload, ctx, resp, op.access if op else "read")
        return resp

    def _notify(self, engine: str, op: str, payload: dict, ctx: ExecutionContext, resp: EngineResponse, access: str) -> None:
        for observer in self._observers:
            try:
                observer(engine, op, payload, ctx, resp, access)
            except Exception:  # noqa: BLE001 - observers must never break execution
                log.exception("Observer failed for %s.%s", engine, op)
