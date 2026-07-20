from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import governance_service
import phase6_runtime  # noqa: F401 — install Phase 1–6 and governance hardening
from governance_models import Department, GovernanceIdentity, GovernanceRole, RoleBinding
from governance_service import has_permission
from main import RuntimeConnector, app, db_session, utcnow
from phase6_app import require_governance
from registry_models import (
    AgentCreate,
    AgentDelegation,
    AgentHeartbeat,
    AgentUpdate,
    DelegationCreate,
    RegisteredAgent,
    agent_view,
    delegation_view,
)
from registry_service import (
    agent_detail,
    create_delegation,
    organization_graph,
    reconcile_workloads,
    registry_stats,
    reliability_from_runs,
    seed_registry,
    skill_matrix,
)

app.version = "0.8.0"

# Add explicit Phase 7 permissions before the governance middleware evaluates requests.
_PHASE7_ROUTE_RULES = [
    ("POST", re.compile(r"^/api/registry/agents$"), "registry:write"),
    ("PATCH", re.compile(r"^/api/registry/agents/[^/]+$"), "registry:write"),
    ("POST", re.compile(r"^/api/registry/agents/[^/]+/heartbeat$"), "registry:heartbeat"),
    ("POST", re.compile(r"^/api/registry/delegations$"), "registry:delegate"),
    ("POST", re.compile(r"^/api/registry/reconcile$"), "registry:write"),
]
for rule in reversed(_PHASE7_ROUTE_RULES):
    if not any(existing[0] == rule[0] and existing[2] == rule[2] and existing[1].pattern == rule[1].pattern for existing in governance_service.ROUTE_RULES):
        governance_service.ROUTE_RULES.insert(0, rule)


def ensure_role_permissions(db: Session) -> None:
    additions = {
        "role:executive": {"registry:read", "registry:write", "registry:delegate"},
        "role:manager": {"registry:read", "registry:write", "registry:delegate"},
        "role:operator": {"registry:read", "registry:heartbeat"},
        "role:auditor": {"registry:read"},
        "role:agent": {"registry:read", "registry:heartbeat"},
        "role:service": {"registry:read", "registry:heartbeat"},
        "role:runtime": {"registry:read"},
    }
    changed = False
    for role_key, permissions in additions.items():
        role = db.scalar(select(GovernanceRole).where(GovernanceRole.role_key == role_key))
        if role is None:
            continue
        current = set(role.permissions or [])
        merged = sorted(current | permissions)
        if merged != role.permissions:
            role.permissions = merged
            role.updated_at = utcnow()
            changed = True
    if changed:
        db.commit()


@app.on_event("startup")
def startup_agent_registry() -> None:
    with next(db_session()) as db:
        ensure_role_permissions(db)
        seed_registry(db)
        reconcile_workloads(db)


def get_agent_or_404(db: Session, agent_key: str) -> RegisteredAgent:
    row = db.scalar(
        select(RegisteredAgent).where(RegisteredAgent.agent_key == agent_key)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Registered agent not found")
    return row


def validate_manager(db: Session, agent_key: str, manager_agent_key: str | None) -> None:
    if not manager_agent_key:
        return
    if manager_agent_key == agent_key:
        raise HTTPException(status_code=409, detail="Agent cannot manage itself")
    manager = db.scalar(
        select(RegisteredAgent).where(
            RegisteredAgent.agent_key == manager_agent_key
        )
    )
    if manager is None:
        raise HTTPException(status_code=409, detail="Manager agent not found")
    visited = {agent_key}
    cursor = manager
    while cursor is not None:
        if cursor.agent_key in visited:
            raise HTTPException(status_code=409, detail="Manager relationship would create a cycle")
        visited.add(cursor.agent_key)
        if not cursor.manager_agent_key:
            break
        cursor = db.scalar(
            select(RegisteredAgent).where(
                RegisteredAgent.agent_key == cursor.manager_agent_key
            )
        )


def ensure_governance_agent_identity(db: Session, payload: AgentCreate, actor: str) -> None:
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == payload.identity_key
        )
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


@app.get("/api/registry/stats")
def read_registry_stats(
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return registry_stats(db)


@app.get("/api/registry/agents")
def list_registered_agents(
    query: str | None = Query(default=None, max_length=200),
    department_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    availability: str | None = Query(default=None, max_length=30),
    runtime_key: str | None = Query(default=None, max_length=80),
    skill: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=250, ge=1, le=1000),
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(RegisteredAgent)
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
            statement.order_by(
                RegisteredAgent.department_key,
                RegisteredAgent.display_name,
            ).limit(limit)
        ).all()
    )
    if skill:
        expected = skill.casefold()
        rows = [row for row in rows if expected in {item.casefold() for item in row.skills or []}]
    return [agent_view(row) for row in rows]


@app.post("/api/registry/agents", status_code=201)
def create_registered_agent(
    payload: AgentCreate,
    actor: str = Depends(require_governance("registry:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if db.scalar(select(RegisteredAgent.id).where(RegisteredAgent.agent_key == payload.agent_key)):
        raise HTTPException(status_code=409, detail="Agent key already exists")
    if db.scalar(select(RegisteredAgent.id).where(RegisteredAgent.identity_key == payload.identity_key)):
        raise HTTPException(status_code=409, detail="Agent identity already exists")
    if db.scalar(select(Department.id).where(Department.department_key == payload.department_key)) is None:
        raise HTTPException(status_code=409, detail="Department not found")
    if db.scalar(select(RuntimeConnector.id).where(RuntimeConnector.runtime_key == payload.preferred_runtime_key)) is None:
        raise HTTPException(status_code=409, detail="Preferred runtime not found")
    validate_manager(db, payload.agent_key, payload.manager_agent_key)
    ensure_governance_agent_identity(db, payload, actor)
    now = utcnow()
    row = RegisteredAgent(
        agent_key=payload.agent_key,
        identity_key=payload.identity_key,
        display_name=payload.display_name,
        role_title=payload.role_title,
        department_key=payload.department_key,
        manager_agent_key=payload.manager_agent_key,
        status="ACTIVE",
        availability="AVAILABLE",
        preferred_runtime_key=payload.preferred_runtime_key,
        preferred_model=payload.preferred_model,
        max_concurrency=payload.max_concurrency,
        current_workload=0,
        reliability_score=0.90,
        successful_runs=0,
        failed_runs=0,
        total_runs=0,
        skills=sorted(set(payload.skills)),
        capabilities=sorted(set(payload.capabilities)),
        allowed_tools=sorted(set(payload.allowed_tools)),
        data_clearance=payload.data_clearance,
        version=payload.version,
        owner_identity=payload.owner_identity,
        profile={**payload.profile, "created_by": actor},
        last_heartbeat_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return agent_detail(db, row)


@app.get("/api/registry/agents/{agent_key}")
def read_registered_agent(
    agent_key: str,
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return agent_detail(db, get_agent_or_404(db, agent_key))


@app.patch("/api/registry/agents/{agent_key}")
def update_registered_agent(
    agent_key: str,
    payload: AgentUpdate,
    actor: str = Depends(require_governance("registry:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = get_agent_or_404(db, agent_key)
    changes = payload.model_dump(exclude_unset=True)
    if "department_key" in changes and db.scalar(
        select(Department.id).where(Department.department_key == changes["department_key"])
    ) is None:
        raise HTTPException(status_code=409, detail="Department not found")
    if "preferred_runtime_key" in changes and db.scalar(
        select(RuntimeConnector.id).where(RuntimeConnector.runtime_key == changes["preferred_runtime_key"])
    ) is None:
        raise HTTPException(status_code=409, detail="Preferred runtime not found")
    if "manager_agent_key" in changes:
        validate_manager(db, agent_key, changes["manager_agent_key"])
    list_fields = {"skills", "capabilities", "allowed_tools"}
    for field, value in changes.items():
        if field in list_fields and value is not None:
            value = sorted(set(value))
        if field == "profile" and value is not None:
            value = {**(row.profile or {}), **value, "updated_by": actor}
        setattr(row, field, value)
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == row.identity_key
        )
    )
    if identity:
        identity.display_name = row.display_name
        identity.department_key = row.department_key
        identity.clearance = row.data_clearance
        identity.status = "ACTIVE" if row.status == "ACTIVE" else "SUSPENDED"
        identity.updated_at = utcnow()
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return agent_detail(db, row)


@app.post("/api/registry/agents/{agent_key}/heartbeat")
def heartbeat_registered_agent(
    agent_key: str,
    payload: AgentHeartbeat,
    actor: str = Depends(require_governance("registry:heartbeat")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = get_agent_or_404(db, agent_key)
    if actor != row.identity_key and not has_permission(db, actor, "registry:write"):
        raise HTTPException(status_code=403, detail="Identity cannot heartbeat another agent")
    row.availability = payload.availability
    if payload.current_workload is not None:
        row.current_workload = payload.current_workload
    row.successful_runs += payload.successful_runs_delta
    row.failed_runs += payload.failed_runs_delta
    row.total_runs = row.successful_runs + row.failed_runs
    row.reliability_score = reliability_from_runs(
        row.successful_runs,
        row.failed_runs,
        row.reliability_score,
    )
    row.profile = {**(row.profile or {}), **payload.profile_patch}
    row.last_heartbeat_at = utcnow()
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return agent_view(row)


@app.get("/api/registry/organization")
def read_organization_graph(
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return organization_graph(db)


@app.get("/api/registry/skills")
def read_skill_matrix(
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    return skill_matrix(db)


@app.get("/api/registry/delegations")
def list_delegations(
    status: str | None = Query(default="ACTIVE", max_length=30),
    agent_key: str | None = Query(default=None, max_length=120),
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(AgentDelegation)
    if status:
        statement = statement.where(AgentDelegation.status == status.upper())
    if agent_key:
        statement = statement.where(
            or_(
                AgentDelegation.source_agent_key == agent_key,
                AgentDelegation.target_agent_key == agent_key,
            )
        )
    rows = db.scalars(
        statement.order_by(AgentDelegation.created_at.desc()).limit(1000)
    ).all()
    return [delegation_view(row) for row in rows]


@app.post("/api/registry/delegations", status_code=201)
def create_agent_delegation(
    payload: DelegationCreate,
    actor: str = Depends(require_governance("registry:delegate")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    try:
        row = create_delegation(
            db,
            source_agent_key=payload.source_agent_key,
            target_agent_key=payload.target_agent_key,
            scope=payload.scope,
            reason=payload.reason,
            ends_at=payload.ends_at,
            created_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return delegation_view(row)


@app.post("/api/registry/reconcile")
def reconcile_agent_registry(
    actor: str = Depends(require_governance("registry:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    result = reconcile_workloads(db)
    return {"ok": True, "actor": actor, **result}
