from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import agent_room_service
from agent_room_models import AgentRoom
from company_blueprint import (
    AGENTS,
    BLUEPRINT_COUNTS,
    BLUEPRINT_VERSION,
    COMPANY_CHARTER,
    COMPANY_KEY,
    DEPARTMENTS,
    MISSIONS,
    TENANT_KEY,
)
from governance_models import Department, GovernanceIdentity, GovernanceRole, RoleBinding
from main import Agent, Mission, MissionEvent, app, db_session, utcnow
from phase6_app import require_governance
from registry_models import AgentDelegation, RegisteredAgent, agent_view

BOOTSTRAP_ENABLED = os.getenv("BEEZA_COMPANY_BOOTSTRAP_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}

ROLE_BY_LEVEL = {
    "board": "role:executive",
    "executive": "role:executive",
    "executive_staff": "role:manager",
    "department": "role:manager",
}

BUDGET_BY_LEVEL = {
    "board": (100.0, 3000.0),
    "executive": (100.0, 3000.0),
    "executive_staff": (75.0, 2000.0),
    "department": (40.0, 1000.0),
}

MISSION_BY_AGENT = {
    "cherry": "EXEC-DAILY-BRIEF-001",
    "rabbit-boss": "COMPANY-LAUNCH-001",
    "cro": "PILOT-FIRST-CUSTOMER-001",
    "head-sales": "PILOT-FIRST-CUSTOMER-001",
}

DELEGATIONS = [
    {
        "source": "ceo",
        "target": "cherry",
        "scope": ["intake", "agenda", "briefing", "follow-up", "decision-log"],
        "reason": "CEO delegates executive office coordination to Cherry while retaining final company accountability.",
    },
    {
        "source": "coo",
        "target": "rabbit-boss",
        "scope": ["work-breakdown", "cross-functional-delivery", "verification", "escalation"],
        "reason": "COO delegates cross-functional execution control to Rabbit Boss within approved missions and governance gates.",
    },
    {
        "source": "cherry",
        "target": "rabbit-boss",
        "scope": ["execution", "task-routing", "evidence-collection"],
        "reason": "Cherry delegates multi-step execution after clarifying the requested outcome and approval boundary.",
    },
]

# Agent Rooms fall back safely, but explicit themes make the new company legible immediately.
agent_room_service.THEME_BY_DEPARTMENT.update(
    {
        "dept:board": "board-midnight",
        "dept:engineering": "engineering-electric",
        "dept:infrastructure": "infrastructure-grid",
        "dept:ai-data": "ai-data-lab",
        "dept:product": "product-studio",
        "dept:growth": "growth-signal",
        "dept:sales": "sales-signal",
        "dept:security": "security-command",
    }
)


def ensure_departments(db: Session) -> tuple[int, int]:
    created = 0
    updated = 0
    now = utcnow()
    for key, spec in DEPARTMENTS.items():
        row = db.scalar(select(Department).where(Department.department_key == key))
        if row is None:
            db.add(
                Department(
                    department_key=key,
                    tenant_key=TENANT_KEY,
                    name=str(spec["name"]),
                    parent_department_key=spec.get("parent"),
                    risk_tier=str(spec["risk"]),
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
            continue

        changed = False
        expected = {
            "tenant_key": TENANT_KEY,
            "name": str(spec["name"]),
            "parent_department_key": spec.get("parent"),
            "risk_tier": str(spec["risk"]),
        }
        for field, value in expected.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        if changed:
            row.updated_at = now
            updated += 1
    db.flush()
    return created, updated


def ensure_governance_identity(db: Session, spec: dict[str, Any]) -> tuple[GovernanceIdentity, bool]:
    identity_key = str(spec["identity_key"])
    row = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == identity_key
        )
    )
    now = utcnow()
    daily, monthly = BUDGET_BY_LEVEL.get(str(spec["level"]), (40.0, 1000.0))
    created = row is None
    if row is None:
        row = GovernanceIdentity(
            identity_key=identity_key,
            tenant_key=TENANT_KEY,
            identity_type="AGENT",
            display_name=str(spec["name"]),
            department_key=str(spec["department"]),
            status="ACTIVE",
            clearance=str(spec["clearance"]),
            daily_budget_usd=daily,
            monthly_budget_usd=monthly,
            attributes={},
            created_at=now,
            updated_at=now,
        )
        db.add(row)

    row.tenant_key = TENANT_KEY
    row.display_name = str(spec["name"])
    row.department_key = str(spec["department"])
    row.status = "ACTIVE"
    row.clearance = str(spec["clearance"])
    row.daily_budget_usd = daily
    row.monthly_budget_usd = monthly
    row.attributes = {
        **(row.attributes or {}),
        "company_key": COMPANY_KEY,
        "company_blueprint": BLUEPRINT_VERSION,
        "organization_level": spec["level"],
        "runtime": spec["runtime"],
        "model": spec["model"],
    }
    row.updated_at = now
    db.flush()

    role_key = ROLE_BY_LEVEL[str(spec["level"])]
    role_exists = db.scalar(
        select(GovernanceRole.id).where(GovernanceRole.role_key == role_key)
    )
    binding = db.scalar(
        select(RoleBinding).where(
            RoleBinding.identity_key == identity_key,
            RoleBinding.role_key == role_key,
            RoleBinding.scope_type == "GLOBAL",
        )
    )
    if role_exists and binding is None:
        db.add(
            RoleBinding(
                binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                identity_key=identity_key,
                role_key=role_key,
                scope_type="GLOBAL",
                scope_key="*",
                created_by="system:company-bootstrap",
                created_at=now,
            )
        )
    return row, created


def ensure_legacy_agent(db: Session, spec: dict[str, Any]) -> bool:
    key = str(spec["key"])
    row = db.scalar(select(Agent).where(Agent.agent_key == key))
    created = row is None
    department_name = str(DEPARTMENTS[str(spec["department"])]["name"])
    if row is None:
        row = Agent(
            agent_key=key,
            name=str(spec["name"]),
            role=str(spec["role"]),
            department=department_name,
            status="AVAILABLE",
            current_mission=MISSION_BY_AGENT.get(key),
            skills=list(spec["skills"]),
        )
        db.add(row)
        return created

    row.name = str(spec["name"])
    row.role = str(spec["role"])
    row.department = department_name
    row.skills = list(spec["skills"])
    if not row.current_mission and key in MISSION_BY_AGENT:
        row.current_mission = MISSION_BY_AGENT[key]
    return created


def ensure_registered_agent(db: Session, spec: dict[str, Any]) -> tuple[RegisteredAgent, bool]:
    key = str(spec["key"])
    row = db.scalar(
        select(RegisteredAgent).where(RegisteredAgent.agent_key == key)
    )
    now = utcnow()
    created = row is None
    if row is None:
        row = RegisteredAgent(
            agent_key=key,
            identity_key=str(spec["identity_key"]),
            display_name=str(spec["name"]),
            role_title=str(spec["role"]),
            department_key=str(spec["department"]),
            manager_agent_key=spec.get("manager"),
            status="ACTIVE",
            availability="AVAILABLE",
            preferred_runtime_key=str(spec["runtime"]),
            preferred_model=str(spec["model"]),
            max_concurrency=int(spec["concurrency"]),
            current_workload=0,
            reliability_score=0.90,
            successful_runs=0,
            failed_runs=0,
            total_runs=0,
            skills=list(spec["skills"]),
            capabilities=list(spec["capabilities"]),
            allowed_tools=list(spec["tools"]),
            data_clearance=str(spec["clearance"]),
            version=BLUEPRINT_VERSION,
            owner_identity="human:owner",
            profile={},
            last_heartbeat_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(row)

    # Structural fields are governed by the company blueprint. Operational counters remain intact.
    row.identity_key = str(spec["identity_key"])
    row.display_name = str(spec["name"])
    row.role_title = str(spec["role"])
    row.department_key = str(spec["department"])
    row.manager_agent_key = spec.get("manager")
    row.status = "ACTIVE"
    row.preferred_runtime_key = str(spec["runtime"])
    row.preferred_model = str(spec["model"])
    row.max_concurrency = int(spec["concurrency"])
    row.skills = sorted(set(spec["skills"]))
    row.capabilities = sorted(set(spec["capabilities"]))
    row.allowed_tools = sorted(set(spec["tools"]))
    row.data_clearance = str(spec["clearance"])
    row.version = BLUEPRINT_VERSION
    row.owner_identity = "human:owner"
    row.profile = {
        **(row.profile or {}),
        "company_key": COMPANY_KEY,
        "company_blueprint": BLUEPRINT_VERSION,
        "organization_level": spec["level"],
        "reports_to": spec.get("manager"),
        "runtime": spec["runtime"],
        "model": spec["model"],
        "seeded": True,
    }
    if row.last_heartbeat_at is None:
        row.last_heartbeat_at = now
    row.updated_at = now
    db.flush()
    return row, created


def ensure_delegations(db: Session) -> int:
    created = 0
    now = utcnow()
    for spec in DELEGATIONS:
        row = db.scalar(
            select(AgentDelegation).where(
                AgentDelegation.source_agent_key == spec["source"],
                AgentDelegation.target_agent_key == spec["target"],
                AgentDelegation.status == "ACTIVE",
            )
        )
        if row is not None:
            row.scope = list(spec["scope"])
            row.reason = str(spec["reason"])
            row.updated_at = now
            continue
        db.add(
            AgentDelegation(
                delegation_key=f"DEL-{uuid4().hex[:14].upper()}",
                source_agent_key=str(spec["source"]),
                target_agent_key=str(spec["target"]),
                scope=list(spec["scope"]),
                reason=str(spec["reason"]),
                status="ACTIVE",
                starts_at=now,
                ends_at=None,
                created_by="system:company-bootstrap",
                created_at=now,
                updated_at=now,
            )
        )
        created += 1
    return created


def ensure_missions(db: Session) -> int:
    created = 0
    now = utcnow()
    for spec in MISSIONS:
        row = db.scalar(
            select(Mission).where(Mission.mission_key == spec["key"])
        )
        if row is not None:
            continue
        db.add(
            Mission(
                mission_key=str(spec["key"]),
                title=str(spec["title"]),
                commander=str(spec["commander"]),
                status=str(spec["status"]),
                priority=str(spec["priority"]),
                progress=int(spec["progress"]),
                waiting_for=str(spec["waiting_for"]),
                objective=str(spec["objective"]),
                created_at=now,
            )
        )
        db.add(
            MissionEvent(
                mission_key=str(spec["key"]),
                actor="Cherry",
                event_type="COMPANY_MISSION_CREATED",
                message="Created from the governed Beeza AI Company blueprint.",
                created_at=now,
            )
        )
        created += 1
    return created


def company_status(db: Session) -> dict[str, Any]:
    expected_agent_keys = {str(item["key"]) for item in AGENTS}
    expected_department_keys = set(DEPARTMENTS)
    expected_mission_keys = {str(item["key"]) for item in MISSIONS}

    agent_rows = list(
        db.scalars(
            select(RegisteredAgent).where(
                RegisteredAgent.agent_key.in_(expected_agent_keys)
            )
        ).all()
    )
    department_rows = list(
        db.scalars(
            select(Department).where(
                Department.department_key.in_(expected_department_keys)
            )
        ).all()
    )
    mission_rows = list(
        db.scalars(
            select(Mission).where(Mission.mission_key.in_(expected_mission_keys))
        ).all()
    )
    room_rows = list(
        db.scalars(
            select(AgentRoom).where(
                AgentRoom.tenant_key == TENANT_KEY,
                AgentRoom.agent_key.in_(expected_agent_keys),
            )
        ).all()
    )

    found_agents = {row.agent_key for row in agent_rows}
    found_departments = {row.department_key for row in department_rows}
    found_missions = {row.mission_key for row in mission_rows}
    room_agents = {row.agent_key for row in room_rows}

    return {
        "company": COMPANY_CHARTER,
        "blueprint_version": BLUEPRINT_VERSION,
        "enabled": BOOTSTRAP_ENABLED,
        "operational": (
            found_agents == expected_agent_keys
            and found_departments == expected_department_keys
            and found_missions == expected_mission_keys
            and room_agents == expected_agent_keys
        ),
        "counts": {
            **BLUEPRINT_COUNTS,
            "registered_agents": len(found_agents),
            "active_agents": sum(row.status == "ACTIVE" for row in agent_rows),
            "departments_ready": len(found_departments),
            "missions_ready": len(found_missions),
            "agent_rooms_ready": len(room_agents),
        },
        "missing": {
            "agents": sorted(expected_agent_keys - found_agents),
            "departments": sorted(expected_department_keys - found_departments),
            "missions": sorted(expected_mission_keys - found_missions),
            "agent_rooms": sorted(expected_agent_keys - room_agents),
        },
        "missions": [
            {
                "key": row.mission_key,
                "title": row.title,
                "commander": row.commander,
                "status": row.status,
                "priority": row.priority,
                "progress": row.progress,
                "waiting_for": row.waiting_for,
            }
            for row in mission_rows
        ],
    }


def bootstrap_company(db: Session) -> dict[str, Any]:
    created_departments, updated_departments = ensure_departments(db)
    created_identities = 0
    created_legacy_agents = 0
    created_registry_agents = 0
    rooms_ready = 0

    # Top-down blueprint order guarantees every manager exists before direct reports.
    for spec in AGENTS:
        _, identity_created = ensure_governance_identity(db, spec)
        created_identities += int(identity_created)
        created_legacy_agents += int(ensure_legacy_agent(db, spec))
        registered, registry_created = ensure_registered_agent(db, spec)
        created_registry_agents += int(registry_created)
        agent_room_service.ensure_room(
            db,
            TENANT_KEY,
            registered,
            actor="system:company-bootstrap",
        )
        rooms_ready += 1

    created_delegations = ensure_delegations(db)
    created_missions = ensure_missions(db)
    db.commit()

    return {
        "company_key": COMPANY_KEY,
        "blueprint_version": BLUEPRINT_VERSION,
        "created": {
            "departments": created_departments,
            "governance_identities": created_identities,
            "legacy_agents": created_legacy_agents,
            "registered_agents": created_registry_agents,
            "delegations": created_delegations,
            "missions": created_missions,
        },
        "updated_departments": updated_departments,
        "rooms_ready": rooms_ready,
        "status": company_status(db),
    }


@app.on_event("startup")
def startup_beeza_ai_company() -> None:
    if not BOOTSTRAP_ENABLED:
        return
    with next(db_session()) as db:
        bootstrap_company(db)


@app.get("/api/company/charter")
def read_company_charter(
    _: str = Depends(require_governance("registry:read")),
) -> dict[str, Any]:
    return {
        "charter": COMPANY_CHARTER,
        "blueprint_version": BLUEPRINT_VERSION,
        "counts": BLUEPRINT_COUNTS,
        "organization": [
            {
                "key": agent["key"],
                "name": agent["name"],
                "role": agent["role"],
                "level": agent["level"],
                "department": agent["department"],
                "manager": agent["manager"],
                "runtime": agent["runtime"],
                "model": agent["model"],
            }
            for agent in AGENTS
        ],
    }


@app.get("/api/company/status")
def read_company_status(
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return company_status(db)


@app.post("/api/company/reconcile")
def reconcile_company(
    actor: str = Depends(require_governance("registry:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    result = bootstrap_company(db)
    result["actor"] = actor
    return result


@app.get("/api/company/agents")
def read_company_agents(
    _: str = Depends(require_governance("registry:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    expected_agent_keys = [str(item["key"]) for item in AGENTS]
    rows = list(
        db.scalars(
            select(RegisteredAgent)
            .where(RegisteredAgent.agent_key.in_(expected_agent_keys))
            .order_by(RegisteredAgent.department_key, RegisteredAgent.display_name)
        ).all()
    )
    return [agent_view(row) for row in rows]
