from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase6_app
from governance_models import (
    ApprovalRequest,
    GovernanceIdentity,
    GovernanceRole,
    RoleBinding,
)
from main import SessionLocal, app


def scoped_role_permissions(
    db: Session,
    identity_key: str,
    mission_key: str | None = None,
) -> list[str]:
    """Resolve only bindings that match the acting identity and resource scope."""
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == identity_key
        )
    )
    if identity is None:
        return []
    bindings = db.scalars(
        select(RoleBinding).where(RoleBinding.identity_key == identity_key)
    ).all()
    role_keys: list[str] = []
    for binding in bindings:
        if binding.scope_type == "GLOBAL":
            role_keys.append(binding.role_key)
        elif binding.scope_type == "TENANT" and binding.scope_key in {
            "*", identity.tenant_key,
        }:
            role_keys.append(binding.role_key)
        elif binding.scope_type == "DEPARTMENT" and binding.scope_key in {
            "*", identity.department_key,
        }:
            role_keys.append(binding.role_key)
        elif (
            binding.scope_type == "MISSION"
            and mission_key
            and binding.scope_key in {"*", mission_key}
        ):
            role_keys.append(binding.role_key)
    if not role_keys:
        return []
    roles = db.scalars(
        select(GovernanceRole).where(GovernanceRole.role_key.in_(role_keys))
    ).all()
    permissions: list[str] = []
    for role in roles:
        permissions.extend(role.permissions or [])
    return sorted(set(permissions))


# Enforcement functions in governance_service resolve the module global at call time.
# Phase 6 API views imported the original symbol, so patch both references.
governance_service.role_permissions = scoped_role_permissions
phase6_app.role_permissions = scoped_role_permissions


def header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


@app.middleware("http")
async def harden_governance_context(request: Request, call_next: Any):
    """Bind approvals to their target and keep recovery calls non-recursive."""
    path = request.url.path
    headers = list(request.scope.get("headers", []))
    changed = False

    approval_key = header_value(headers, b"x-beeza-approval-key").strip()
    if approval_key:
        identity_key = (
            header_value(headers, b"x-beeza-identity").strip()
            or governance_service.DEFAULT_IDENTITY
        )
        with SessionLocal() as db:
            approval = db.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.approval_key == approval_key
                )
            )
        if (
            approval is None
            or approval.requester_identity != identity_key
            or approval.target not in {"*", path}
        ):
            headers = [
                (name, value)
                for name, value in headers
                if name.lower() != b"x-beeza-approval-key"
            ]
            changed = True

    if path.startswith("/api/governance/"):
        headers = [
            (name, value)
            for name, value in headers
            if name.lower() not in {
                b"x-beeza-estimated-cost-usd",
                b"x-beeza-risk-level",
            }
        ]
        headers.extend(
            [
                (b"x-beeza-estimated-cost-usd", b"0"),
                (b"x-beeza-risk-level", b"NORMAL"),
            ]
        )
        changed = True

    if changed:
        request.scope["headers"] = headers
        if hasattr(request, "_headers"):
            delattr(request, "_headers")
    return await call_next(request)
