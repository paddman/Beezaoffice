from __future__ import annotations

from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase10_app  # noqa: F401 — install Phase 1–10 routes and workers
from evaluation_models import EvaluationRun, ReplayRun
from main import (
    Agent,
    RuntimeConnector,
    app,
    db_session,
    engine,
    redis_client,
)
from registry_models import RegisteredAgent
from sop_models import SOPRun, SOPTemplate, SOPVersion

app.version = "0.11.0"


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method.upper() in getattr(route, "methods", set())
        )
    ]


remove_route("/api/health", "GET")


@app.get("/api/health")
def sop_health(
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
    evaluator = redis_client.hgetall("beezaoffice:evaluator-worker")
    sop = redis_client.hgetall("beezaoffice:sop-worker")
    active_sop_runs = db.query(SOPRun).filter(
        SOPRun.status.in_(["PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK"])
    ).count()
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
        "evaluator": evaluator.get("status", "starting"),
        "evaluator_last_tick_at": evaluator.get("last_tick_at"),
        "evaluation_runs": db.query(EvaluationRun).count(),
        "replay_runs": db.query(ReplayRun).count(),
        "sop_worker": sop.get("status", "starting"),
        "sop_last_tick_at": sop.get("last_tick_at"),
        "sop_templates": db.query(SOPTemplate).count(),
        "sop_versions": db.query(SOPVersion).count(),
        "sop_runs": db.query(SOPRun).count(),
        "sop_active_runs": active_sop_runs,
        "governance": "enforced",
        "phase": 10,
    }
