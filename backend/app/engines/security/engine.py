"""Security engine: validation, threat detection, prompt-injection screening,
policy evaluation and security event logging. Fully deterministic."""
from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation

from . import policy
from .detectors import THREAT_RULES, prompt_injection_scan, threat_scan

MAX_TEXT = 200_000


class TextInput(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT, description="Text to analyse")
    source: str | None = Field(None, max_length=200, description="Optional label for logging (e.g. message id)")


class FieldRule(BaseModel):
    name: str = Field(..., max_length=100)
    value: Any = None
    type: Literal["string", "email", "url", "ipv4", "ipv6", "uuid", "integer", "number", "alphanumeric",
                  "iso_date", "safe_filename"] = "string"
    required: bool = True
    min_length: int | None = Field(None, ge=0)
    max_length: int | None = Field(None, ge=1, le=100_000)
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = Field(None, max_length=200, description="Anchored regex (full match)")


class ValidateInput(BaseModel):
    fields: list[FieldRule] = Field(..., min_length=1, max_length=200)


class AuthorizeInput(BaseModel):
    role: str = Field(..., max_length=32)
    actor_type: Literal["human", "ai", "system"] = "human"
    permission: str = Field(..., max_length=100, examples=["crypto:sign"])
    access: Literal["read", "write", "sensitive"] = "sensitive"


class EventsInput(BaseModel):
    limit: int = Field(50, ge=1, le=500)


class EmptyInput(BaseModel):
    pass


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,63}$")
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]{0,2040}$", re.IGNORECASE)
SAFE_FILENAME_RE = re.compile(r"^(?!\.)[A-Za-z0-9 _.\-]{1,255}$")


def _check_field(rule: FieldRule) -> list[str]:
    v = rule.value
    if v is None or v == "":
        return ["is required"] if rule.required else []
    errors: list[str] = []
    s = str(v)
    if len(s) > 100_000:
        return ["value too long to validate"]
    t = rule.type
    try:
        if t == "email" and not EMAIL_RE.match(s):
            errors.append("is not a valid email address")
        elif t == "url" and not URL_RE.match(s):
            errors.append("is not a valid http(s) URL")
        elif t == "ipv4":
            ipaddress.IPv4Address(s)
        elif t == "ipv6":
            ipaddress.IPv6Address(s)
        elif t == "uuid":
            uuid.UUID(s)
        elif t == "integer":
            if isinstance(v, bool) or not re.fullmatch(r"[+-]?\d+", s):
                errors.append("is not an integer")
        elif t == "number":
            float(s)
        elif t == "alphanumeric" and not s.isalnum():
            errors.append("must be alphanumeric")
        elif t == "iso_date":
            date.fromisoformat(s)
        elif t == "safe_filename" and (not SAFE_FILENAME_RE.match(s) or ".." in s):
            errors.append("is not a safe filename")
    except ValueError:
        errors.append(f"is not a valid {t}")
    if rule.min_length is not None and len(s) < rule.min_length:
        errors.append(f"must be at least {rule.min_length} characters")
    if rule.max_length is not None and len(s) > rule.max_length:
        errors.append(f"must be at most {rule.max_length} characters")
    if t in ("integer", "number") and not errors:
        num = float(s)
        if rule.minimum is not None and num < rule.minimum:
            errors.append(f"must be >= {rule.minimum}")
        if rule.maximum is not None and num > rule.maximum:
            errors.append(f"must be <= {rule.maximum}")
    if rule.pattern:
        try:
            if not re.fullmatch(rule.pattern, s[:10_000]):
                errors.append("does not match the required pattern")
        except re.error:
            errors.append("validation pattern is invalid")
    return errors


class SecurityEngine(BaseEngine):
    name = "security"
    title = "Security Engine"
    description = "Input validation, threat detection, prompt-injection screening, access policy and security events."

    def __init__(self, store=None) -> None:
        super().__init__()
        self.store = store

    def authorizer(self, ctx: ExecutionContext, permission: str, access: str) -> tuple[bool, str]:
        """Registry hook: the single deterministic gate for every operation."""
        return policy.check(ctx, permission, access)

    def _log(self, ctx: ExecutionContext, action: str, severity: str, detail: dict) -> None:
        if self.store is not None:
            self.store.audit("security", action, actor=ctx.actor, role=ctx.role, severity=severity, detail=detail)

    @operation("threat_scan", TextInput, description="Detect injection payloads, exposed secrets, phishing language and suspicious URLs")
    def op_threat_scan(self, data: TextInput, ctx: ExecutionContext) -> OpResult:
        result = threat_scan(data.text)
        if result["risk_band"] in ("high", "critical"):
            self._log(ctx, "threat_detected", "warning", {
                "source": data.source, "risk_score": result["risk_score"],
                "rules": [f["rule"] for f in result["findings"]][:20]})
        return OpResult(result=result, metadata={"method": "deterministic pattern rules + URL heuristics",
                                                 "rules_evaluated": len(THREAT_RULES)})

    @operation("prompt_injection", TextInput, description="Screen untrusted text before it reaches an LLM")
    def op_prompt_injection(self, data: TextInput, ctx: ExecutionContext) -> OpResult:
        result = prompt_injection_scan(data.text)
        if result["verdict"] != "allow":
            self._log(ctx, f"prompt_injection_{result['verdict']}", "warning", {
                "source": data.source, "score": result["injection_score"],
                "rules": [s["rule"] for s in result["signals"]]})
        return OpResult(result=result, metadata={"method": "deterministic heuristics; not exhaustive"})

    @operation("validate", ValidateInput, description="Validate typed input fields against declarative rules")
    def op_validate(self, data: ValidateInput, ctx: ExecutionContext) -> OpResult:
        errors = {}
        for rule in data.fields:
            errs = _check_field(rule)
            if errs:
                errors[rule.name] = errs
        return OpResult(result={"valid": not errors, "errors": errors, "checked": len(data.fields)})

    @operation("authorize", AuthorizeInput, description="Evaluate the access policy for a hypothetical actor (grants nothing)")
    def op_authorize(self, data: AuthorizeInput, ctx: ExecutionContext) -> OpResult:
        probe = ExecutionContext(actor="policy-probe", role=data.role, actor_type=data.actor_type)
        allowed, reason = policy.check(probe, data.permission, data.access)
        return OpResult(result={"allowed": allowed, "reason": reason, "role": data.role,
                                "actor_type": data.actor_type, "permission": data.permission})

    @operation("policy", EmptyInput, description="Describe the active role/permission policy")
    def op_policy(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result=policy.describe())

    @operation("events", EventsInput, description="Recent security events from the audit log")
    def op_events(self, data: EventsInput, ctx: ExecutionContext) -> OpResult:
        if self.store is None:
            raise EngineError("NO_STORE", "Security event storage is not configured", 503)
        return OpResult(result={"events": self.store.list_audit(limit=data.limit, category="security")})
