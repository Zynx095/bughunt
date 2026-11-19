"""Shared data contracts used by every engine and API route."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

Access = Literal["read", "write", "sensitive"]
ActorType = Literal["human", "ai", "system"]


class EngineErrorInfo(BaseModel):
    code: str
    message: str
    details: Any = None


class EngineResponse(BaseModel):
    """The universal response envelope returned by every engine operation.

    `confidence` is null whenever a meaningful confidence cannot be calculated
    (e.g. deterministic cryptographic results or uncalibrated anomaly scores).
    `error` is an extension of the base contract and is null on success.
    """

    success: bool
    engine: str
    result: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    execution_time_ms: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: EngineErrorInfo | None = None

    # HTTP status to use when this envelope is returned by the API (not serialised).
    _status: int = PrivateAttr(default=200)


@dataclass
class OpResult:
    """What an operation handler returns; the engine wraps it in an EngineResponse."""

    result: dict[str, Any]
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Who is executing what. Identity here is *declared*, not authenticated —
    plug a real identity provider in front of the API before deployment."""

    actor: str = "anonymous"
    role: str = "analyst"
    actor_type: ActorType = "human"
    run_id: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def child(self, **changes: Any) -> "ExecutionContext":
        data = {**self.__dict__, **changes}
        data["request_id"] = uuid.uuid4().hex[:16]
        return ExecutionContext(**data)


class EngineError(Exception):
    """Raised by operation handlers for expected, user-facing failures."""

    def __init__(self, code: str, message: str, status: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details
