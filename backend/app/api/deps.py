"""Request-scoped dependencies."""
from __future__ import annotations

import re

from fastapi import Header, HTTPException, Request

from app.core.contracts import ExecutionContext
from app.engines.security.policy import ROLE_PERMISSIONS
from app.services import Services

ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@\-]{1,64}$")


def services(request: Request) -> Services:
    return request.app.state.services


def context(
    request: Request,
    x_omniforge_role: str | None = Header(None),
    x_omniforge_actor: str | None = Header(None),
    x_omniforge_actor_type: str | None = Header(None),
) -> ExecutionContext:
    """Build the execution context from *declared* identity headers.

    SECURITY NOTE: this is a simulated identity for the foundation build. Put a
    real authentication layer (OIDC/JWT) in front before exposing the API.
    Clients may only downgrade themselves to actor_type 'ai'; 'system' is internal.
    """
    settings = request.app.state.services.settings
    role = (x_omniforge_role or settings.default_role).lower()
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"Unknown role '{role}'. Valid roles: {sorted(ROLE_PERMISSIONS)}")
    actor = x_omniforge_actor or f"demo-{role}"
    if not ACTOR_RE.match(actor):
        raise HTTPException(400, "Invalid actor name")
    actor_type = (x_omniforge_actor_type or "human").lower()
    if actor_type not in ("human", "ai"):
        raise HTTPException(400, "actor_type must be 'human' or 'ai'")
    return ExecutionContext(actor=actor, role=role, actor_type=actor_type)  # type: ignore[arg-type]


def require(svc: Services, ctx: ExecutionContext, permission: str, access: str = "write") -> None:
    allowed, reason = svc.registry.authorizer(ctx, permission, access)
    if not allowed:
        svc.store.audit("security", "access_denied", actor=ctx.actor, role=ctx.role, severity="warning",
                        detail={"permission": permission, "reason": reason})
        raise HTTPException(403, reason)
