"""Base class and operation decorator shared by all engines.

An engine is a named collection of *operations*. Each operation declares:
  * a Pydantic input model (input validation + JSON schema for docs/UI),
  * an access level (read / write / sensitive) used by the policy layer,
  * an optional explicit permission string (defaults to "<engine>:<access>").

`BaseEngine.execute` provides the uniform lifecycle: validate -> run -> wrap in
the common EngineResponse envelope with timing, warnings and error handling.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ValidationError

from .contracts import Access, EngineError, EngineErrorInfo, EngineResponse, ExecutionContext, OpResult

if TYPE_CHECKING:  # pragma: no cover
    from .registry import EngineRegistry

log = logging.getLogger("omniforge.engine")


@dataclass
class Operation:
    name: str
    handler: Callable[[Any, ExecutionContext], OpResult]
    input_model: type[BaseModel]
    description: str
    access: Access
    permission: str

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "access": self.access,
            "permission": self.permission,
            "input_schema": self.input_model.model_json_schema(),
        }


def operation(
    name: str,
    input_model: type[BaseModel],
    *,
    description: str = "",
    access: Access = "read",
    permission: str | None = None,
):
    """Mark an engine method as a callable operation."""

    def decorator(fn):
        fn._op_meta = {
            "name": name,
            "input_model": input_model,
            "description": description or (fn.__doc__ or "").strip().split("\n")[0],
            "access": access,
            "permission": permission,
        }
        return fn

    return decorator


class BaseEngine:
    name: str = "base"
    title: str = "Base engine"
    description: str = ""

    def __init__(self) -> None:
        self.registry: "EngineRegistry | None" = None
        self.initialised = False
        self.operations: dict[str, Operation] = {}
        for attr in dir(type(self)):
            fn = getattr(type(self), attr, None)
            meta = getattr(fn, "_op_meta", None)
            if meta:
                permission = meta["permission"] or f"{self.name}:{meta['access']}"
                self.operations[meta["name"]] = Operation(
                    name=meta["name"],
                    handler=getattr(self, attr),
                    input_model=meta["input_model"],
                    description=meta["description"],
                    access=meta["access"],
                    permission=permission,
                )

    # ---- lifecycle -----------------------------------------------------
    def initialise(self, registry: "EngineRegistry") -> None:
        self.registry = registry
        self.on_initialise()
        self.initialised = True

    def on_initialise(self) -> None:
        """Hook for subclasses (load models, connect providers, ...)."""

    def health(self) -> dict[str, Any]:
        return {"status": "ok" if self.initialised else "not_initialised"}

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "health": self.health(),
            "operations": [op.describe() for op in self.operations.values()],
        }

    # ---- execution -----------------------------------------------------
    def get_operation(self, op_name: str) -> Operation:
        op = self.operations.get(op_name)
        if op is None:
            raise EngineError(
                "UNKNOWN_OPERATION",
                f"Engine '{self.name}' has no operation '{op_name}'",
                status=404,
                details={"available": sorted(self.operations)},
            )
        return op

    def validate(self, op_name: str, payload: dict[str, Any]) -> BaseModel:
        return self.get_operation(op_name).input_model.model_validate(payload or {})

    def execute(self, op_name: str, payload: dict[str, Any], ctx: ExecutionContext) -> EngineResponse:
        started = time.perf_counter()
        meta = {"operation": op_name, "request_id": ctx.request_id}
        status = 200
        try:
            op = self.get_operation(op_name)
            data = self.validate(op_name, payload)
            out = op.handler(data, ctx)
            response = EngineResponse(
                success=True,
                engine=self.name,
                result=out.result,
                confidence=out.confidence,
                warnings=out.warnings,
                metadata={**meta, **out.metadata},
            )
        except ValidationError as exc:
            status = 422
            response = self._failure(meta, "INVALID_INPUT", "Input validation failed", _clean_errors(exc))
        except EngineError as exc:
            status = exc.status
            response = self._failure(meta, exc.code, exc.message, exc.details)
        except Exception as exc:  # noqa: BLE001 - engine boundary
            log.exception("Unhandled error in %s.%s", self.name, op_name)
            status = 500
            response = self._failure(meta, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
        response.execution_time_ms = round((time.perf_counter() - started) * 1000, 3)
        response._status = status
        return response

    def _failure(self, meta: dict, code: str, message: str, details: Any = None) -> EngineResponse:
        return EngineResponse(
            success=False,
            engine=self.name,
            metadata=meta,
            error=EngineErrorInfo(code=code, message=message, details=details),
        )

    # ---- helpers for engines that call other engines --------------------
    def call(self, engine: str, op: str, payload: dict[str, Any], ctx: ExecutionContext) -> EngineResponse:
        if self.registry is None:
            raise EngineError("NOT_INITIALISED", f"Engine '{self.name}' is not attached to a registry", 500)
        return self.registry.execute(engine, op, payload, ctx)


def _clean_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
