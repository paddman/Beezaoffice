from __future__ import annotations

from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

import phase14_app
from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT
from main import SessionLocal, app

_original_feature_for_request = phase14_app.feature_for_request


def commercial_feature_for_request(method: str, path: str) -> str | None:
    if method.upper() == "POST" and path == "/api/enterprise/tenants":
        return "enterprise"
    return _original_feature_for_request(method, path)


phase14_app.feature_for_request = commercial_feature_for_request


@app.middleware("http")
async def licensed_tenant_quota(request: Request, call_next: Callable):
    if request.method.upper() != "POST" or request.url.path != "/api/enterprise/tenants":
        return await call_next(request)
    tenant_key = request.headers.get("X-Beeza-Tenant", DEFAULT_TENANT)
    with SessionLocal() as db:
        state = phase14_app.license_state(db, tenant_key)
        if state["valid"]:
            limit = phase14_app.entitlement_limit(db, tenant_key, "max_tenants", 0)
            active = int(
                db.scalar(
                    select(func.count(EnterpriseTenant.id)).where(
                        EnterpriseTenant.status == "ACTIVE"
                    )
                )
                or 0
            )
            if limit and active >= limit:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "Licensed tenant limit reached",
                        "limit": limit,
                        "active": active,
                    },
                )
    return await call_next(request)
