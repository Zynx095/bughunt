"""Deterministic access-control policy (RBAC + actor-type caps).

Security-critical decisions are made here with plain rules — never by an LLM.
Roles are *declared* by the client in this foundation build (see README:
"Identity is simulated"); swap `ExecutionContext` population for a real
identity provider before any deployment.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from app.core.contracts import ExecutionContext

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "viewer": ["*:read"],
    "analyst": ["*:read", "*:write", "pipeline:run", "crypto:sign"],
    "reviewer": ["*:read", "*:write", "pipeline:run", "crypto:sign", "crypto:decrypt", "approval:decide"],
    "admin": ["*"],
}

# AI/LLM-originated actions are capped at read-only compute, whatever the role.
AI_ALLOWED_ACCESS = {"read"}
# Belt and braces: permissions an AI actor can never hold.
AI_DENIED_PERMISSIONS = {"approval:decide", "crypto:sign", "crypto:decrypt", "crypto:write", "settings:write"}


def check(ctx: ExecutionContext, permission: str, access: str) -> tuple[bool, str]:
    role = ctx.role
    if role not in ROLE_PERMISSIONS:
        return False, f"Unknown role '{role}'"
    if ctx.actor_type == "ai":
        if access not in AI_ALLOWED_ACCESS or permission in AI_DENIED_PERMISSIONS:
            return False, (f"AI-originated actions may not perform '{permission}' ({access}); "
                           "a human with an authorised role must perform it")
    for pattern in ROLE_PERMISSIONS[role]:
        if fnmatchcase(permission, pattern):
            return True, f"role '{role}' grants '{permission}' via '{pattern}'"
    return False, f"role '{role}' lacks permission '{permission}'"


def describe() -> dict:
    return {
        "roles": ROLE_PERMISSIONS,
        "ai_actor": {"allowed_access": sorted(AI_ALLOWED_ACCESS), "always_denied": sorted(AI_DENIED_PERMISSIONS)},
        "notes": [
            "Permissions default to '<engine>:<access>' unless an operation declares its own.",
            "Approvals additionally forbid self-approval (requester cannot decide their own request).",
        ],
    }
