from __future__ import annotations

import re
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import phase10_app
import phase12_app
from enterprise_service import DEFAULT_TENANT, resource_tenant, scope_resource
from main import SessionLocal, app, db_session
from phase6_app import require_governance
from sop_models import SOPTemplateCreate

SOPDeriveRequest = phase10_app.SOPDeriveRequest


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


_ORIGINAL_CREATE_TEMPLATE = phase10_app.create_sop_template
_ORIGINAL_DERIVE_TEMPLATE = phase10_app.derive_sop_from_mission

remove_route("/api/sop/templates", "POST")
remove_route("/api/sop/derive/{mission_key}", "POST")


@app.post("/api/sop/templates", status_code=201)
def create_tenant_sop_template(
    payload: SOPTemplateCreate,
    tenant_key: str = Depends(phase12_app.tenant_header),
    actor: str = Depends(require_governance("sop:write")),
    db: Session = Depends(db_session),
):
    result = _ORIGINAL_CREATE_TEMPLATE(payload=payload, actor=actor, db=db)
    scope_resource(
        db,
        "sop_template",
        payload.template_key,
        tenant_key,
        created_by=actor,
    )
    db.commit()
    return {**result, "tenant_key": tenant_key}


@app.post("/api/sop/derive/{mission_key}", status_code=201)
def derive_tenant_sop_template(
    mission_key: str,
    payload: SOPDeriveRequest,
    tenant_key: str = Depends(phase12_app.tenant_header),
    actor: str = Depends(require_governance("sop:write")),
    db: Session = Depends(db_session),
):
    owner = resource_tenant(db, "mission", mission_key) or DEFAULT_TENANT
    if owner != tenant_key:
        raise HTTPException(status_code=404, detail="Mission not found")
    result = _ORIGINAL_DERIVE_TEMPLATE(
        mission_key=mission_key,
        payload=payload,
        actor=actor,
        db=db,
    )
    scope_resource(
        db,
        "sop_template",
        payload.template_key,
        tenant_key,
        created_by=actor,
    )
    db.commit()
    return {**result, "tenant_key": tenant_key}


@app.middleware("http")
async def sop_tenant_ownership(request: Request, call_next: Callable):
    path = request.url.path
    tenant_key = request.headers.get("X-Beeza-Tenant", DEFAULT_TENANT)
    template_key = None
    version_template_key = None

    match = re.match(r"^/api/sop/templates/([^/]+)", path)
    if match:
        template_key = match.group(1)
    match = re.match(r"^/api/sop/versions/([^/]+)/publish$", path)
    if match:
        version_key = match.group(1)
        version_template_key = version_key.split(":v", 1)[0]

    key = template_key or version_template_key
    if key:
        with SessionLocal() as db:
            owner = resource_tenant(db, "sop_template", key)
            if owner is not None and owner != tenant_key:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "SOP template not found"},
                )
    return await call_next(request)
