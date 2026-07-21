from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase11_app  # noqa: F401 — install Phase 1–11 protocol gateway
from governance_service import has_permission
from main import Agent, RuntimeConnector, app, db_session, engine, redis_client
from protocol_models import ProtocolTask
from registry_models import RegisteredAgent
from sop_models import SOPRun, SOPTemplate

app.version = "0.12.0"
_TASK_PATH = re.compile(r"^/tasks/([^/:]+)(?::subscribe|:cancel)?$")


@app.middleware("http")
async def protocol_task_scope_middleware(request: Request, call_next: Callable):
    match = _TASK_PATH.match(request.url.path)
    if match and request.method.upper() in {"GET", "POST"}:
        task_id = match.group(1)
        actor = request.headers.get("X-Beeza-Identity", "service:protocol").strip() or "service:protocol"
        with phase11_app.SessionLocal() as db:
            row = db.scalar(select(ProtocolTask).where(ProtocolTask.task_id == task_id))
            if row is not None and row.client_identity != actor and not has_permission(db, actor, "protocol:operate"):
                return JSONResponse(status_code=404, content={"detail": "Protocol task not found"})
    return await call_next(request)


app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/health"
        and "GET" in getattr(route, "methods", set())
    )
]


@app.get("/api/health")
def protocol_health(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    database = "ok"
    queue = "ok"
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        database = "error"
    try:
        redis_client.ping()
    except Exception:
        queue = "error"

    runtimes = list(
        db.scalars(select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)).all()
    )
    has_registry = db.scalar(select(RegisteredAgent.id).limit(1)) is not None
    registered_agents = db.query(RegisteredAgent).count() if has_registry else db.query(Agent).count()
    active_agents = (
        db.query(RegisteredAgent).filter(RegisteredAgent.status == "ACTIVE").count()
        if has_registry else registered_agents
    )
    protocol_tasks = db.query(ProtocolTask).count()
    active_protocol_tasks = db.query(ProtocolTask).filter(
        ProtocolTask.state.not_in(phase11_app.TERMINAL_PROTOCOL_STATES)
    ).count()
    worker = redis_client.hgetall("beezaoffice:protocol-worker")
    return {
        "status": "ok" if database == queue == "ok" else "degraded",
        "database": database,
        "queue": queue,
        "registered_agents": registered_agents,
        "active_agents": active_agents,
        "registry_scale_target": 1000,
        "runtime_connectors": len(runtimes),
        "runtime_online": sum(row.status == "ONLINE" for row in runtimes),
        "runtime_configured": sum(bool(row.base_url) for row in runtimes),
        "sop_templates": db.query(SOPTemplate).count(),
        "active_sop_runs": db.query(SOPRun).filter(
            SOPRun.status.in_(["PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK"])
        ).count(),
        "protocol_tasks": protocol_tasks,
        "active_protocol_tasks": active_protocol_tasks,
        "protocol_worker": worker.get("status", "starting"),
        "protocols": ["a2a-1.0", "mcp-2025-06-18", "openai-chat", "webhook", "sse"],
        "governance": "enforced",
        "phase": 11,
    }
