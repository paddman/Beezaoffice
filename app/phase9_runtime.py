from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase9_app  # noqa: F401 — install Phase 1–9 routes and workers
import evaluation_hardening  # noqa: F401 — stable hashes and replay preference enforcement
import evaluation_startup_fix  # noqa: F401 — schema-first evaluator identity bootstrap
from evaluation_models import EvaluationRun, ReplayRun
from governance_models import GovernanceIdentity, RoleBinding
from main import (
    Agent,
    RuntimeConnector,
    SessionLocal,
    app,
    db_session,
    engine,
    redis_client,
    utcnow,
)
from registry_models import RegisteredAgent

app.version = "0.10.0"

# Creating a replay can enqueue and dispatch a second execution, so it obeys the kill switch.
governance_service.EXECUTION_ACTIONS.add("replay:create")


@app.on_event("startup")
def seed_evaluator_service_identity() -> None:
    with SessionLocal() as db:
        now = utcnow()
        identity_key = "service:evaluator"
        identity = db.scalar(
            select(GovernanceIdentity).where(
                GovernanceIdentity.identity_key == identity_key
            )
        )
        if identity is None:
            db.add(
                GovernanceIdentity(
                    identity_key=identity_key,
                    tenant_key="tenant:beeza",
                    identity_type="SERVICE",
                    display_name="Beeza Evidence Evaluator",
                    department_key="dept:quality",
                    status="ACTIVE",
                    clearance="RESTRICTED",
                    daily_budget_usd=1000.0,
                    monthly_budget_usd=30000.0,
                    attributes={
                        "seeded": True,
                        "purpose": "evidence evaluation, verification and replay comparison",
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
        binding = db.scalar(
            select(RoleBinding).where(
                RoleBinding.identity_key == identity_key,
                RoleBinding.role_key == "role:service",
                RoleBinding.scope_type == "GLOBAL",
                RoleBinding.scope_key == "*",
            )
        )
        if binding is None:
            db.add(
                RoleBinding(
                    binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                    identity_key=identity_key,
                    role_key="role:service",
                    scope_type="GLOBAL",
                    scope_key="*",
                    created_by="system:phase9",
                    created_at=now,
                )
            )
        db.commit()


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
def evaluation_health(
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
        "governance": "enforced",
        "phase": 9,
    }
