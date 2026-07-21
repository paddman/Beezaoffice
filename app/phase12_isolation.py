from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

import phase10_app
import phase12_app
from collaboration_models import (
    CollaborationMessage,
    CollaborationTask,
    MESSAGE_STATUSES,
    TASK_STATUSES,
    message_view,
    task_view,
)
from enterprise_service import DEFAULT_TENANT, resource_tenant, scoped_keys
from governance_models import GovernanceIdentity
from main import RuntimeDispatch, app, db_session
from phase2_app import phase2_dispatch_view
from phase6_app import require_governance
from protocol_models import ProtocolEvent
from registry_models import RegisteredAgent, agent_view
from registry_service import agent_detail
from sop_models import SOPRun, SOPTemplate, run_view, template_view, version_view
from sop_service import published_version


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
    ("/api/registry/agents", "GET"),
    ("/api/registry/agents/{agent_key}", "GET"),
    ("/api/collaboration/tasks", "GET"),
    ("/api/collaboration/inbox", "GET"),
    ("/api/runtime-dispatches", "GET"),
    ("/api/protocol/events", "GET"),
    ("/api/sop/templates", "GET"),
    ("/api/sop/runs", "GET"),
]:
    remove_route(route_path, method)


@app.get("/api/registry/agents")
def list_tenant_agents(
    query: str | None = Query(default=None, max_length=200),
    department_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    availability: str | None = Query(default=None, max_length=30),
    runtime_key: str | None = Query(default=None, max_length=80),
    skill: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=250, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = (
        select(RegisteredAgent)
        .join(
            GovernanceIdentity,
            GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
        )
        .where(GovernanceIdentity.tenant_key == tenant_key)
    )
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                RegisteredAgent.agent_key.ilike(pattern),
                RegisteredAgent.display_name.ilike(pattern),
                RegisteredAgent.role_title.ilike(pattern),
                RegisteredAgent.identity_key.ilike(pattern),
            )
        )
    if department_key:
        statement = statement.where(RegisteredAgent.department_key == department_key)
    if status:
        statement = statement.where(RegisteredAgent.status == status.upper())
    if availability:
        statement = statement.where(RegisteredAgent.availability == availability.upper())
    if runtime_key:
        statement = statement.where(RegisteredAgent.preferred_runtime_key == runtime_key)
    rows = list(
        db.scalars(
            statement.order_by(RegisteredAgent.department_key, RegisteredAgent.display_name).limit(limit)
        ).all()
    )
    if skill:
        expected = skill.casefold()
        rows = [row for row in rows if expected in {item.casefold() for item in row.skills or []}]
    return [agent_view(row) for row in rows]


@app.get("/api/registry/agents/{agent_key}")
def read_tenant_agent(
    agent_key: str,
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(RegisteredAgent)
        .join(
            GovernanceIdentity,
            GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
        )
        .where(
            RegisteredAgent.agent_key == agent_key,
            GovernanceIdentity.tenant_key == tenant_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Registered agent not found")
    return agent_detail(db, row)


@app.get("/api/collaboration/tasks")
def list_tenant_collaboration_tasks(
    mission_key: str | None = None,
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("api:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    if mission_key:
        if mission_key not in mission_keys:
            raise HTTPException(status_code=404, detail="Mission not found")
        mission_keys = [mission_key]
    if not mission_keys:
        return []
    statement = select(CollaborationTask).where(CollaborationTask.mission_key.in_(mission_keys))
    if status:
        normalized = status.upper()
        if normalized not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown task status")
        statement = statement.where(CollaborationTask.status == normalized)
    rows = db.scalars(statement.order_by(CollaborationTask.created_at.desc()).limit(limit)).all()
    return [task_view(row) for row in rows]


@app.get("/api/collaboration/inbox")
def list_tenant_collaboration_inbox(
    recipient: str | None = None,
    mission_key: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("api:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    if mission_key:
        if mission_key not in mission_keys:
            raise HTTPException(status_code=404, detail="Mission not found")
        mission_keys = [mission_key]
    if not mission_keys:
        return []
    statement = select(CollaborationMessage).where(CollaborationMessage.mission_key.in_(mission_keys))
    if recipient:
        statement = statement.where(CollaborationMessage.target_identity == recipient)
    if status:
        normalized = status.upper()
        if normalized not in MESSAGE_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown message status")
        statement = statement.where(CollaborationMessage.status == normalized)
    rows = db.scalars(statement.order_by(CollaborationMessage.created_at.desc()).limit(limit)).all()
    return [message_view(row) for row in rows]


@app.get("/api/runtime-dispatches")
def list_tenant_runtime_dispatches(
    mission_key: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("api:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    if mission_key:
        if mission_key not in mission_keys:
            raise HTTPException(status_code=404, detail="Mission not found")
        mission_keys = [mission_key]
    if not mission_keys:
        return []
    rows = db.scalars(
        select(RuntimeDispatch)
        .where(RuntimeDispatch.mission_key.in_(mission_keys))
        .order_by(RuntimeDispatch.created_at.desc())
        .limit(limit)
    ).all()
    return [phase2_dispatch_view(row) for row in rows]


@app.get("/api/protocol/events")
def list_tenant_protocol_events(
    task_id: str | None = Query(default=None, max_length=120),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    task_ids = scoped_keys(db, "protocol_task", tenant_key)
    if task_id:
        if task_id not in task_ids:
            raise HTTPException(status_code=404, detail="Protocol task not found")
        task_ids = [task_id]
    if not task_ids:
        return []
    rows = db.scalars(
        select(ProtocolEvent)
        .where(ProtocolEvent.task_id.in_(task_ids), ProtocolEvent.sequence > after)
        .order_by(ProtocolEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "key": row.event_key,
            "task_id": row.task_id,
            "sequence": row.sequence,
            "type": row.event_type,
            "payload": row.payload,
            "occurred_at": row.occurred_at.isoformat(),
        }
        for row in rows
    ]


@app.get("/api/sop/templates")
def list_tenant_sop_templates(
    status: str | None = Query(default=None, max_length=30),
    category: str | None = Query(default=None, max_length=100),
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    template_keys = scoped_keys(db, "sop_template", tenant_key)
    if not template_keys:
        return []
    statement = select(SOPTemplate).where(SOPTemplate.template_key.in_(template_keys))
    if status:
        statement = statement.where(SOPTemplate.status == status.upper())
    if category:
        statement = statement.where(SOPTemplate.category == category)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            SOPTemplate.name.ilike(pattern) | SOPTemplate.description.ilike(pattern)
        )
    rows = db.scalars(statement.order_by(SOPTemplate.category, SOPTemplate.name).limit(limit)).all()
    tenant_run_keys = scoped_keys(db, "sop_run", tenant_key)
    result: list[dict[str, Any]] = []
    for row in rows:
        version = published_version(db, row)
        run_count = 0
        if tenant_run_keys:
            run_count = db.scalar(
                select(func.count(SOPRun.id)).where(
                    SOPRun.run_key.in_(tenant_run_keys),
                    SOPRun.template_key == row.template_key,
                )
            ) or 0
        result.append(
            {
                **template_view(row),
                "published_version": version_view(version) if version else None,
                "run_count": int(run_count),
                "tenant_key": tenant_key,
            }
        )
    return result


@app.get("/api/sop/runs")
def list_tenant_sop_runs(
    template_key: str | None = Query(default=None, max_length=100),
    mission_key: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_key: str = Depends(phase12_app.tenant_header),
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    run_keys = scoped_keys(db, "sop_run", tenant_key)
    if not run_keys:
        return []
    statement = select(SOPRun).where(SOPRun.run_key.in_(run_keys))
    if template_key:
        statement = statement.where(SOPRun.template_key == template_key)
    if mission_key:
        statement = statement.where(SOPRun.mission_key == mission_key)
    if status:
        statement = statement.where(SOPRun.status == status.upper())
    rows = db.scalars(statement.order_by(SOPRun.created_at.desc()).limit(limit)).all()
    return [{**run_view(row), "tenant_key": tenant_key} for row in rows]
