from __future__ import annotations

import contextvars
import fnmatch
import re
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import phase10_app
import phase11_app
import phase11_hardening
import phase12_app  # noqa: F401 — install Phase 1–12 enterprise APIs
import protocol_service
import sop_service
from collaboration_models import CollaborationTask
from enterprise_models import EnterpriseApiKey, EnterpriseSession, EnterpriseTenant, ResourceScope
from enterprise_service import (
    DEFAULT_TENANT,
    api_key_scope_allowed,
    authenticate_api_key,
    authenticate_session,
    rate_limit,
    resource_tenant,
    scope_resource,
    scoped_keys,
    seed_enterprise,
)
from governance_models import GovernanceIdentity
from governance_service import has_permission, permission_for_request
from main import (
    AUTH_TOKEN,
    Mission,
    MissionCreate,
    MissionEvent,
    RuntimeConnector,
    RuntimeDispatch,
    SessionLocal,
    app,
    db_session,
    engine,
    redis_client,
    utcnow,
)
from phase2_app import phase2_dispatch_view
from phase6_app import require_governance
from protocol_models import ProtocolTask, protocol_task_view
from registry_models import RegisteredAgent
from sop_models import SOPRun, SOPTemplate

app.version = "0.13.0"
current_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "beeza_enterprise_tenant", default=DEFAULT_TENANT
)


def replace_header(scope: dict[str, Any], name: str, value: str) -> None:
    target = name.lower().encode()
    headers = [(key, val) for key, val in scope.get("headers", []) if key.lower() != target]
    headers.append((target, value.encode()))
    scope["headers"] = headers


def identity_tenant(db: Session, identity_key: str) -> str | None:
    return db.scalar(
        select(GovernanceIdentity.tenant_key).where(
            GovernanceIdentity.identity_key == identity_key,
            GovernanceIdentity.status == "ACTIVE",
        )
    )


def mission_for_request(db: Session, request: Request) -> str | None:
    path = request.url.path
    match = re.match(r"^/api/missions/([^/]+)", path)
    if match:
        return match.group(1)
    query_mission = request.query_params.get("mission_key")
    if query_mission:
        return query_mission
    match = re.match(r"^/tasks/([^/:]+)", path)
    if match:
        return db.scalar(
            select(ProtocolTask.mission_key).where(ProtocolTask.task_id == match.group(1))
        )
    match = re.match(r"^/api/runtime-dispatches/([^/]+)", path)
    if match:
        return db.scalar(
            select(RuntimeDispatch.mission_key).where(
                RuntimeDispatch.dispatch_key == match.group(1)
            )
        )
    match = re.match(r"^/api/collaboration/tasks/([^/]+)", path)
    if match:
        return db.scalar(
            select(CollaborationTask.mission_key).where(
                CollaborationTask.task_key == match.group(1)
            )
        )
    match = re.match(r"^/api/sop/runs/([^/]+)", path)
    if match:
        return db.scalar(
            select(SOPRun.mission_key).where(SOPRun.run_key == match.group(1))
        )
    return None


@app.middleware("http")
async def enterprise_auth_isolation(request: Request, call_next: Callable):
    path = request.url.path
    public = path in {
        "/enterprise/sso/oidc/exchange",
        "/health/live",
        "/health/ready",
        "/metrics",
        "/.well-known/agent-card.json",
    }
    authorization = request.headers.get("Authorization", "")
    bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
    identity_key = request.headers.get("X-Beeza-Identity", "human:owner").strip() or "human:owner"
    requested_tenant = request.headers.get("X-Beeza-Tenant", "").strip()
    authenticated_tenant: str | None = None
    key_row: EnterpriseApiKey | None = None

    with SessionLocal() as db:
        if bearer and bearer != AUTH_TOKEN:
            session = authenticate_session(db, bearer)
            if session is not None:
                identity_key = session.identity_key
                authenticated_tenant = session.tenant_key
            else:
                key_row = authenticate_api_key(db, bearer)
                if key_row is not None:
                    identity_key = key_row.identity_key
                    authenticated_tenant = key_row.tenant_key
            if session is None and key_row is None and not public:
                return JSONResponse(status_code=401, content={"detail": "Invalid enterprise session or API key"})
            if session is not None or key_row is not None:
                replace_header(request.scope, "Authorization", f"Bearer {AUTH_TOKEN}")
                replace_header(request.scope, "X-Beeza-Identity", identity_key)

        base_tenant = authenticated_tenant or identity_tenant(db, identity_key) or DEFAULT_TENANT
        tenant_key = requested_tenant or base_tenant
        if tenant_key != base_tenant and not has_permission(db, identity_key, "enterprise:tenant:manage"):
            return JSONResponse(status_code=403, content={"detail": "Identity cannot switch enterprise tenant"})
        tenant = db.scalar(
            select(EnterpriseTenant).where(
                EnterpriseTenant.tenant_key == tenant_key,
                EnterpriseTenant.status == "ACTIVE",
            )
        )
        if tenant is None and not public:
            return JSONResponse(status_code=403, content={"detail": "Enterprise tenant is not active"})

        if key_row is not None:
            permission = permission_for_request(request.method, path)
            if not api_key_scope_allowed(key_row, permission):
                return JSONResponse(status_code=403, content={"detail": f"API key scope does not allow {permission}"})

        if not public and tenant is not None:
            limit = key_row.rate_limit_per_minute if key_row else tenant.requests_per_minute
            allowed, remaining, reset = rate_limit(tenant_key, identity_key, limit)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(reset), "X-RateLimit-Remaining": "0"},
                    content={"detail": "Enterprise rate limit exceeded", "tenant_key": tenant_key},
                )
            mission_key = mission_for_request(db, request)
            if mission_key:
                owner = resource_tenant(db, "mission", mission_key) or DEFAULT_TENANT
                if owner != tenant_key:
                    return JSONResponse(status_code=404, content={"detail": "Resource not found"})
        db.commit()

    replace_header(request.scope, "X-Beeza-Tenant", tenant_key)
    token = current_tenant.set(tenant_key)
    try:
        response = await call_next(request)
        if not public and tenant is not None:
            response.headers["X-Beeza-Tenant"] = tenant_key
            response.headers["X-RateLimit-Policy"] = f"{limit};w=60"
        return response
    finally:
        current_tenant.reset(token)


# Scope all internally generated protocol tasks and SOP runs to the active tenant.
_original_create_protocol_task = protocol_service.create_protocol_task


async def enterprise_create_protocol_task(db: Session, *args, **kwargs):
    row = await _original_create_protocol_task(db, *args, **kwargs)
    tenant_key = current_tenant.get()
    if row.mission_key:
        scope_resource(db, "mission", row.mission_key, tenant_key)
    scope_resource(db, "protocol_task", row.task_id, tenant_key)
    db.commit()
    return row


protocol_service.create_protocol_task = enterprise_create_protocol_task
phase11_app.create_protocol_task = enterprise_create_protocol_task
phase11_hardening._original_create_protocol_task = enterprise_create_protocol_task

_original_instantiate_run = sop_service.instantiate_run


def enterprise_instantiate_run(db: Session, *args, **kwargs):
    run = _original_instantiate_run(db, *args, **kwargs)
    tenant_key = current_tenant.get()
    scope_resource(db, "mission", run.mission_key, tenant_key)
    scope_resource(db, "sop_run", run.run_key, tenant_key)
    scope_resource(db, "sop_template", run.template_key, tenant_key)
    db.commit()
    return run


sop_service.instantiate_run = enterprise_instantiate_run
phase10_app.instantiate_run = enterprise_instantiate_run
phase11_app.instantiate_run = enterprise_instantiate_run


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


for route_path, method in [
    ("/api/missions", "GET"),
    ("/api/missions", "POST"),
    ("/api/missions/{mission_key}", "GET"),
    ("/api/protocol/tasks", "GET"),
    ("/api/health", "GET"),
]:
    remove_route(route_path, method)


def mission_view(row: Mission) -> dict[str, Any]:
    return {
        "key": row.mission_key,
        "title": row.title,
        "commander": row.commander,
        "status": row.status,
        "priority": row.priority,
        "progress": row.progress,
        "waiting_for": row.waiting_for,
        "objective": row.objective,
    }


@app.get("/api/missions")
def list_tenant_missions(
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("api:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    keys = scoped_keys(db, "mission", tenant_key)
    if not keys:
        return []
    rows = db.scalars(
        select(Mission).where(Mission.mission_key.in_(keys)).order_by(Mission.created_at.desc())
    ).all()
    return [mission_view(row) for row in rows]


@app.post("/api/missions", status_code=201)
def create_tenant_mission(
    payload: MissionCreate,
    tenant_key: str = Depends(phase12_app.tenant_header),
    actor: str = Depends(require_governance("mission:create")),
    db: Session = Depends(db_session),
) -> dict[str, str]:
    tenant = db.scalar(select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == tenant_key))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    sequence = int(redis_client.incr(f"beezaoffice:mission-sequence:{tenant.slug}"))
    key = f"{tenant.slug.upper()}-{utcnow():%Y%m%d}-{sequence:04d}"
    mission = Mission(
        mission_key=key,
        title=payload.title,
        commander="Beeza Commander",
        status="PLANNING",
        priority=payload.priority,
        progress=5,
        waiting_for="Dynamic team formation",
        objective=payload.objective,
        created_at=utcnow(),
    )
    db.add(mission)
    db.add(
        MissionEvent(
            mission_key=key,
            actor=actor,
            event_type="MISSION_CREATED",
            message=f"Tenant-scoped mission accepted for {tenant_key}.",
            created_at=utcnow(),
        )
    )
    scope_resource(db, "mission", key, tenant_key, created_by=actor)
    db.commit()
    return {"key": key, "status": "PLANNING", "tenant_key": tenant_key}


@app.get("/api/missions/{mission_key}")
def read_tenant_mission(
    mission_key: str,
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("api:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if (resource_tenant(db, "mission", mission_key) or DEFAULT_TENANT) != tenant_key:
        raise HTTPException(status_code=404, detail="Mission not found")
    mission = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    events = db.scalars(
        select(MissionEvent).where(MissionEvent.mission_key == mission_key).order_by(MissionEvent.id)
    ).all()
    dispatches = db.scalars(
        select(RuntimeDispatch).where(RuntimeDispatch.mission_key == mission_key).order_by(RuntimeDispatch.created_at.desc())
    ).all()
    return {
        **mission_view(mission),
        "tenant_key": tenant_key,
        "events": [
            {
                "actor": row.actor,
                "type": row.event_type,
                "message": row.message,
                "created_at": row.created_at.isoformat(),
            }
            for row in events
        ],
        "dispatches": [phase2_dispatch_view(row) for row in dispatches],
    }


@app.get("/api/protocol/tasks")
def list_tenant_protocol_tasks(
    protocol: str | None = Query(default=None, max_length=40),
    state: str | None = Query(default=None, max_length=50),
    mission_key: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    keys = scoped_keys(db, "protocol_task", tenant_key)
    if not keys:
        return []
    statement = select(ProtocolTask).where(ProtocolTask.task_id.in_(keys))
    if protocol:
        statement = statement.where(ProtocolTask.protocol == protocol.lower())
    if state:
        statement = statement.where(ProtocolTask.state == state.upper())
    if mission_key:
        statement = statement.where(ProtocolTask.mission_key == mission_key)
    rows = db.scalars(statement.order_by(ProtocolTask.created_at.desc()).limit(limit)).all()
    return [protocol_task_view(row) for row in rows]


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive", "version": app.version}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    database = True
    queue = True
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        database = False
    try:
        redis_client.ping()
    except Exception:
        queue = False
    status = 200 if database and queue else 503
    return JSONResponse(
        status_code=status,
        content={"status": "ready" if status == 200 else "not_ready", "database": database, "queue": queue},
    )


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(db: Session = Depends(db_session)) -> str:
    tenants = db.scalar(select(func.count(EnterpriseTenant.id))) or 0
    missions = db.scalar(select(func.count(Mission.id))) or 0
    agents = db.scalar(select(func.count(RegisteredAgent.id))) or 0
    active_dispatches = db.scalar(
        select(func.count(RuntimeDispatch.id)).where(
            RuntimeDispatch.status.in_(["DISPATCHING", "RUNNING", "QUEUED", "WAITING_APPROVAL"])
        )
    ) or 0
    protocol_tasks = db.scalar(select(func.count(ProtocolTask.id))) or 0
    return "\n".join([
        "# HELP beeza_enterprise_tenants Registered enterprise tenants.",
        "# TYPE beeza_enterprise_tenants gauge",
        f"beeza_enterprise_tenants {tenants}",
        "# HELP beeza_missions_total Durable missions.",
        "# TYPE beeza_missions_total gauge",
        f"beeza_missions_total {missions}",
        "# HELP beeza_registered_agents Registered logical agents.",
        "# TYPE beeza_registered_agents gauge",
        f"beeza_registered_agents {agents}",
        "# HELP beeza_active_runtime_dispatches Active runtime dispatches.",
        "# TYPE beeza_active_runtime_dispatches gauge",
        f"beeza_active_runtime_dispatches {active_dispatches}",
        "# HELP beeza_protocol_tasks_total Protocol gateway tasks.",
        "# TYPE beeza_protocol_tasks_total gauge",
        f"beeza_protocol_tasks_total {protocol_tasks}",
        "",
    ])


@app.get("/api/health")
def enterprise_health(db: Session = Depends(db_session)) -> dict[str, Any]:
    ready = True
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        redis_client.ping()
    except Exception:
        ready = False
    runtimes = list(db.scalars(select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)).all())
    return {
        "status": "ok" if ready else "degraded",
        "phase": 12,
        "version": app.version,
        "enterprise_tenants": db.scalar(select(func.count(EnterpriseTenant.id))) or 0,
        "registered_agents": db.scalar(select(func.count(RegisteredAgent.id))) or 0,
        "runtime_connectors": len(runtimes),
        "runtime_online": sum(row.status == "ONLINE" for row in runtimes),
        "runtime_configured": sum(bool(row.base_url) for row in runtimes),
        "tenant_isolation": "row-enforced",
        "enterprise_auth": ["platform-token", "oidc-session", "scoped-api-key"],
        "observability": ["health", "readiness", "prometheus"],
        "governance": "enforced",
    }
