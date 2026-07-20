from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase8_app  # noqa: F401 — install Phase 1–8 routes and workers
from collaboration_models import CollaborationTask, TERMINAL_TASK_STATUSES, task_view
from main import (
    Agent,
    RuntimeConnector,
    app,
    db_session,
    engine,
    redis_client,
    utcnow,
)
from phase6_app import require_governance
from registry_models import RegisteredAgent
from scheduler_models import decision_view
from scheduler_service import route_task

app.version = "0.9.0"


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method.upper() in getattr(route, "methods", set())
        )
    ]


remove_route("/api/scheduler/tasks/{task_key}/route", "POST")
remove_route("/api/health", "GET")


@app.post("/api/scheduler/tasks/{task_key}/route")
def safe_reroute_task(
    task_key: str,
    actor: str = Depends(require_governance("scheduler:route")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    task = db.scalar(
        select(CollaborationTask).where(CollaborationTask.task_key == task_key)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    if task.status in TERMINAL_TASK_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Terminal task cannot be rerouted from {task.status}",
        )
    if task.status in {"DISPATCHING", "RUNNING", "WAITING_APPROVAL", "REVIEW"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task is {task.status}. Stop or complete the active remote dispatch "
                "before rerouting to prevent duplicate execution."
            ),
        )
    context = dict(task.context or {})
    routing = dict(context.get("routing") or {})
    excluded_agents = list(context.get("excluded_agents") or [])
    excluded_runtimes = list(context.get("excluded_runtimes") or [])
    if routing.get("selected_agent_key"):
        excluded_agents.append(routing["selected_agent_key"])
    if routing.get("selected_runtime_key"):
        excluded_runtimes.append(routing["selected_runtime_key"])
    routing.update({
        "mode": str(
            context.get("routing_mode") or routing.get("mode") or "FAILOVER"
        ).upper(),
        "status": "WAITING",
        "next_route_at": utcnow().isoformat(),
    })
    context.update({
        "routing": routing,
        "routing_mode": routing["mode"],
        "excluded_agents": list(dict.fromkeys(excluded_agents)),
        "excluded_runtimes": list(dict.fromkeys(excluded_runtimes)),
        "force_reroute": True,
    })
    task.context = context
    task.target_identity = "agent:auto"
    task.target_runtime_key = "auto"
    task.dispatch_key = None
    task.status = "QUEUED"
    task.updated_at = utcnow()
    decision = route_task(db, task, actor=actor, force=True)
    db.commit()
    db.refresh(task)
    return {
        "task": task_view(task),
        "decision": decision_view(decision) if decision else None,
    }


@app.get("/api/health")
def scheduler_health(
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
    registry_exists = db.scalar(select(RegisteredAgent.id).limit(1)) is not None
    registered_agents = (
        db.query(RegisteredAgent).count()
        if registry_exists
        else db.query(Agent).count()
    )
    active_agents = (
        db.query(RegisteredAgent)
        .filter(RegisteredAgent.status == "ACTIVE")
        .count()
        if registry_exists
        else registered_agents
    )
    scheduler = redis_client.hgetall("beezaoffice:scheduler-worker")
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
        "scheduler": scheduler.get("status", "starting"),
        "scheduler_last_tick_at": scheduler.get("last_tick_at"),
        "governance": "enforced",
        "phase": 8,
    }
