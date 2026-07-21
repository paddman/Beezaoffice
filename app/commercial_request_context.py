from __future__ import annotations

from typing import Any, Callable

from fastapi import Request
from sqlalchemy import select

from enterprise_service import (
    DEFAULT_TENANT,
    authenticate_api_key,
    authenticate_session,
)
from governance_models import GovernanceIdentity
from governance_service import has_permission
from main import AUTH_TOKEN, SessionLocal, app


def replace_header(scope: dict[str, Any], name: str, value: str) -> None:
    target = name.lower().encode()
    headers = [
        (key, current)
        for key, current in scope.get("headers", [])
        if key.lower() != target
    ]
    headers.append((target, value.encode()))
    scope["headers"] = headers


def resolve_commercial_tenant(request: Request) -> str:
    requested = request.headers.get("X-Beeza-Tenant", "").strip()
    authorization = request.headers.get("Authorization", "")
    bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
    identity_key = (
        request.headers.get("X-Beeza-Identity", "human:owner").strip()
        or "human:owner"
    )
    with SessionLocal() as db:
        authenticated_tenant = None
        if bearer and bearer != AUTH_TOKEN:
            session = authenticate_session(db, bearer)
            if session is not None:
                identity_key = session.identity_key
                authenticated_tenant = session.tenant_key
            else:
                api_key = authenticate_api_key(db, bearer)
                if api_key is not None:
                    identity_key = api_key.identity_key
                    authenticated_tenant = api_key.tenant_key
        identity_tenant = db.scalar(
            select(GovernanceIdentity.tenant_key).where(
                GovernanceIdentity.identity_key == identity_key,
                GovernanceIdentity.status == "ACTIVE",
            )
        )
        base_tenant = authenticated_tenant or identity_tenant or DEFAULT_TENANT
        tenant_key = base_tenant
        if requested and requested != base_tenant:
            if has_permission(db, identity_key, "enterprise:tenant:manage"):
                tenant_key = requested
        elif requested:
            tenant_key = requested
        db.commit()
    return tenant_key


@app.middleware("http")
async def commercial_tenant_context(request: Request, call_next: Callable):
    tenant_key = resolve_commercial_tenant(request)
    replace_header(request.scope, "X-Beeza-Tenant", tenant_key)
    return await call_next(request)
