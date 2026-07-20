from __future__ import annotations

from collections import Counter
from datetime import timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase7_app
import registry_service
from collaboration_models import CollaborationTask
from governance_models import GovernanceIdentity, RoleBinding
from main import (
    Agent,
    RuntimeConnector,
    app,
    db_session,
    engine,
    redis_client,
    utcnow,
)
from registry_models import RegisteredAgent

app.version = "0.8.0"


def aware(value):
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hardened_reconcile_workloads(
    db: Session,
    stale_seconds: int = registry_service.HEARTBEAT_STALE_SECONDS,
) -> dict[str, Any]:
    agents = list(db.scalars(select(RegisteredAgent)).all())
    tasks = list(
        db.scalars(
            select(CollaborationTask).where(
                CollaborationTask.status.in_(registry_service.ACTIVE_TASK_STATUSES)
            )
        ).all()
    )
    workload = Counter()
    for task in tasks:
        target = registry_service.normalize_identity(task.target_identity)
        if target:
            workload[target] += 1
    now = utcnow()
    stale_cutoff = now - timedelta(seconds=max(30, stale_seconds))
    changed = 0
    for agent in agents:
        aliases = {
            registry_service.normalize_identity(agent.agent_key),
            registry_service.normalize_identity(agent.identity_key),
            registry_service.normalize_identity(agent.display_name),
        }
        count = sum(workload.get(alias, 0) for alias in aliases)
        count = min(agent.max_concurrency * 10, count)
        availability = agent.availability
        heartbeat = aware(agent.last_heartbeat_at)
        if agent.status != "ACTIVE":
            availability = "OFFLINE"
        elif heartbeat and heartbeat < stale_cutoff:
            availability = "OFFLINE"
        elif count > 0:
            availability = "BUSY"
        elif availability in {"BUSY", "WAITING"}:
            availability = "AVAILABLE"
        if count != agent.current_workload or availability != agent.availability:
            agent.current_workload = count
            agent.availability = availability
            agent.updated_at = now
            changed += 1
    expired = registry_service.expire_delegations(db)
    db.commit()
    return {
        "registered_agents": len(agents),
        "active_tasks": len(tasks),
        "changed_agents": changed,
        "expired_delegations": expired,
        "reconciled_at": now.isoformat(),
    }


def hardened_ensure_governance_agent_identity(
    db: Session,
    payload,
    actor: str,
) -> None:
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == payload.identity_key
        )
    )
    if identity is not None and identity.identity_type != "AGENT":
        raise HTTPException(
            status_code=409,
            detail="Identity key is already registered to a non-agent principal",
        )
    if identity is None:
        identity = GovernanceIdentity(
            identity_key=payload.identity_key,
            tenant_key="tenant:beeza",
            identity_type="AGENT",
            display_name=payload.display_name,
            department_key=payload.department_key,
            status="ACTIVE",
            clearance=payload.data_clearance,
            daily_budget_usd=50.0,
            monthly_budget_usd=1000.0,
            attributes={"registry_agent_key": payload.agent_key, "created_by": actor},
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(identity)
        db.flush()
    binding = db.scalar(
        select(RoleBinding).where(
            RoleBinding.identity_key == payload.identity_key,
            RoleBinding.role_key == "role:agent",
            RoleBinding.scope_type == "GLOBAL",
            RoleBinding.scope_key == "*",
        )
    )
    if binding is None:
        db.add(
            RoleBinding(
                binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                identity_key=payload.identity_key,
                role_key="role:agent",
                scope_type="GLOBAL",
                scope_key="*",
                created_by=actor,
                created_at=utcnow(),
            )
        )


registry_service.reconcile_workloads = hardened_reconcile_workloads
phase7_app.reconcile_workloads = hardened_reconcile_workloads
phase7_app.ensure_governance_agent_identity = hardened_ensure_governance_agent_identity


# Replace the original fixed-count health route with a registry-aware response.
app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/health"
        and "GET" in getattr(route, "methods", set())
    )
]


@app.get("/api/health")
def registry_health(
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
    registry_count = db.scalar(select(RegisteredAgent.id).limit(1))
    registered_agents = db.query(RegisteredAgent).count() if registry_count else db.query(Agent).count()
    active_agents = db.query(RegisteredAgent).filter(RegisteredAgent.status == "ACTIVE").count() if registry_count else registered_agents
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
        "governance": "enforced",
        "phase": 7,
    }
