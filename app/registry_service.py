from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask
from governance_models import Department, GovernanceIdentity
from main import Agent, RuntimeConnector, utcnow
from registry_models import AgentDelegation, RegisteredAgent, agent_view, delegation_view

ACTIVE_TASK_STATUSES = {
    "WAITING_DEPENDENCY", "QUEUED", "DISPATCHING", "RUNNING", "REVIEW",
    "BLOCKED", "REVISION", "ESCALATED",
}
HEARTBEAT_STALE_SECONDS = 300


def normalize_identity(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("agent:"):
        text = text[6:]
    return "".join(char for char in text if char.isalnum() or char in {"-", "_", "."})


def department_key_for(name: str) -> str:
    mapping = {
        "Executive": "dept:executive",
        "Operations": "dept:operations",
        "Data": "dept:data",
        "Quality": "dept:quality",
        "Finance": "dept:finance",
        "Support": "dept:support",
        "People": "dept:people",
        "Legal": "dept:legal",
        "Procurement": "dept:procurement",
        "Marketing": "dept:marketing",
    }
    return mapping.get(name, "dept:platform")


def seed_registry(db: Session) -> None:
    if db.scalar(select(RegisteredAgent.id).limit(1)) is not None:
        return
    base_agents = list(db.scalars(select(Agent).order_by(Agent.id)).all())
    manager_map = {
        "mira": None,
        "rei": "mira",
        "aiden": "rei",
        "noah": "rei",
        "yuna": "rei",
        "leon": "mira",
        "irene": "leon",
        "kai": "leon",
        "luna": "mira",
        "claire": "mira",
        "selene": "mira",
        "aria": "mira",
    }
    runtime_map = {
        "rei": "cherryagent",
        "aiden": "openclaw",
        "noah": "hermes",
        "yuna": "thclaws",
        "mira": "cherryagent",
        "leon": "hermes",
        "irene": "thclaws",
        "luna": "cherryagent",
        "claire": "cherryagent",
        "selene": "hermes",
        "kai": "openclaw",
        "aria": "thclaws",
    }
    clearance_map = {
        "Operations": "RESTRICTED",
        "Finance": "CONFIDENTIAL",
        "Legal": "CONFIDENTIAL",
        "People": "CONFIDENTIAL",
        "Executive": "RESTRICTED",
    }
    max_concurrency_map = {
        "rei": 4,
        "mira": 5,
        "leon": 3,
        "aiden": 3,
        "noah": 3,
        "yuna": 3,
    }
    reliability_map = {
        "rei": 0.96,
        "aiden": 0.94,
        "noah": 0.92,
        "yuna": 0.95,
        "mira": 0.97,
        "leon": 0.93,
        "irene": 0.91,
        "luna": 0.90,
        "claire": 0.89,
        "selene": 0.94,
        "kai": 0.90,
        "aria": 0.88,
    }
    now = utcnow()
    for source in base_agents:
        identity_key = f"agent:{source.agent_key}"
        governance_identity = db.scalar(
            select(GovernanceIdentity).where(
                GovernanceIdentity.identity_key == identity_key
            )
        )
        if governance_identity is None:
            department_key = department_key_for(source.department)
        else:
            department_key = governance_identity.department_key or department_key_for(source.department)
        availability = {
            "RUNNING": "BUSY",
            "WAITING": "WAITING",
            "AVAILABLE": "AVAILABLE",
        }.get(source.status, "OFFLINE")
        capabilities = list(dict.fromkeys([
            source.role.lower().replace(" ", "-"),
            f"department:{source.department.lower()}",
            *source.skills,
        ]))
        tools = {
            "Operations": ["shell", "prometheus", "proxmox", "runbook"],
            "Data": ["sql", "python", "metrics", "forecast"],
            "Quality": ["evidence", "policy-check", "test-runner"],
            "Finance": ["ledger", "forecast", "vendor-analysis"],
            "Legal": ["contract-review", "privacy-check"],
            "Marketing": ["content", "analytics"],
        }.get(source.department, ["search", "document", "report"])
        db.add(
            RegisteredAgent(
                agent_key=source.agent_key,
                identity_key=identity_key,
                display_name=source.name,
                role_title=source.role,
                department_key=department_key,
                manager_agent_key=manager_map.get(source.agent_key),
                status="ACTIVE",
                availability=availability,
                preferred_runtime_key=runtime_map.get(source.agent_key, "cherryagent"),
                preferred_model="",
                max_concurrency=max_concurrency_map.get(source.agent_key, 2),
                current_workload=1 if source.current_mission else 0,
                reliability_score=reliability_map.get(source.agent_key, 0.90),
                successful_runs=0,
                failed_runs=0,
                total_runs=0,
                skills=source.skills,
                capabilities=capabilities,
                allowed_tools=tools,
                data_clearance=clearance_map.get(source.department, "INTERNAL"),
                version="1.0.0",
                owner_identity="human:owner",
                profile={
                    "legacy_status": source.status,
                    "current_mission": source.current_mission,
                    "avatar_slot": source.agent_key,
                    "seeded": True,
                },
                last_heartbeat_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()


def expire_delegations(db: Session) -> int:
    now = utcnow()
    rows = db.scalars(
        select(AgentDelegation).where(
            AgentDelegation.status == "ACTIVE",
            AgentDelegation.ends_at.is_not(None),
            AgentDelegation.ends_at <= now,
        )
    ).all()
    for row in rows:
        row.status = "EXPIRED"
        row.updated_at = now
    if rows:
        db.commit()
    return len(rows)


def reconcile_workloads(db: Session, stale_seconds: int = HEARTBEAT_STALE_SECONDS) -> dict[str, Any]:
    agents = list(db.scalars(select(RegisteredAgent)).all())
    tasks = list(
        db.scalars(
            select(CollaborationTask).where(
                CollaborationTask.status.in_(ACTIVE_TASK_STATUSES)
            )
        ).all()
    )
    workload = Counter()
    for task in tasks:
        target = normalize_identity(task.target_identity)
        if target:
            workload[target] += 1
    now = utcnow()
    stale_cutoff = now - timedelta(seconds=max(30, stale_seconds))
    changed = 0
    for agent in agents:
        aliases = {
            normalize_identity(agent.agent_key),
            normalize_identity(agent.identity_key),
            normalize_identity(agent.display_name),
        }
        count = sum(workload.get(alias, 0) for alias in aliases)
        count = min(agent.max_concurrency * 10, count)
        availability = agent.availability
        if agent.status != "ACTIVE":
            availability = "OFFLINE"
        elif agent.last_heartbeat_at and agent.last_heartbeat_at < stale_cutoff:
            availability = "OFFLINE"
        elif count >= agent.max_concurrency:
            availability = "BUSY"
        elif count > 0:
            availability = "BUSY"
        elif availability in {"BUSY", "WAITING"}:
            availability = "AVAILABLE"
        if count != agent.current_workload or availability != agent.availability:
            agent.current_workload = count
            agent.availability = availability
            agent.updated_at = now
            changed += 1
    expire_delegations(db)
    db.commit()
    return {
        "registered_agents": len(agents),
        "active_tasks": len(tasks),
        "changed_agents": changed,
        "reconciled_at": now.isoformat(),
    }


def registry_stats(db: Session) -> dict[str, Any]:
    agents = list(db.scalars(select(RegisteredAgent)).all())
    departments = Counter(agent.department_key for agent in agents)
    runtimes = Counter(agent.preferred_runtime_key for agent in agents)
    availability = Counter(agent.availability for agent in agents)
    active = [agent for agent in agents if agent.status == "ACTIVE"]
    total_capacity = sum(agent.max_concurrency for agent in active)
    workload = sum(agent.current_workload for agent in active)
    weighted_reliability = (
        sum(agent.reliability_score for agent in active) / len(active)
        if active else 0.0
    )
    return {
        "registered_agents": len(agents),
        "active_agents": len(active),
        "departments": len(departments),
        "skills": len({skill for agent in agents for skill in agent.skills}),
        "total_capacity": total_capacity,
        "current_workload": workload,
        "available_capacity": max(0, total_capacity - workload),
        "utilization": round(workload / total_capacity, 4) if total_capacity else 0.0,
        "average_reliability": round(weighted_reliability, 4),
        "availability": dict(sorted(availability.items())),
        "runtime_distribution": dict(sorted(runtimes.items())),
        "department_distribution": dict(sorted(departments.items())),
        "scale_target": 1000,
    }


def skill_matrix(db: Session) -> list[dict[str, Any]]:
    agents = list(db.scalars(select(RegisteredAgent).order_by(RegisteredAgent.display_name)).all())
    matrix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for agent in agents:
        for skill in sorted(set(agent.skills)):
            matrix[skill].append({
                "agent_key": agent.agent_key,
                "name": agent.display_name,
                "department_key": agent.department_key,
                "availability": agent.availability,
                "reliability_score": agent.reliability_score,
                "available_capacity": max(0, agent.max_concurrency - agent.current_workload),
            })
    return [
        {
            "skill": skill,
            "agent_count": len(members),
            "available_count": sum(member["available_capacity"] > 0 for member in members),
            "average_reliability": round(
                sum(member["reliability_score"] for member in members) / len(members), 4
            ),
            "agents": members,
        }
        for skill, members in sorted(matrix.items())
    ]


def organization_graph(db: Session) -> dict[str, Any]:
    agents = list(db.scalars(select(RegisteredAgent).order_by(RegisteredAgent.display_name)).all())
    departments = list(db.scalars(select(Department).order_by(Department.name)).all())
    runtime_map = {
        row.runtime_key: row.display_name
        for row in db.scalars(select(RuntimeConnector)).all()
    }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for department in departments:
        nodes.append({
            "id": department.department_key,
            "type": "department",
            "label": department.name,
            "risk_tier": department.risk_tier,
            "parent": department.parent_department_key,
        })
        if department.parent_department_key:
            edges.append({
                "source": department.parent_department_key,
                "target": department.department_key,
                "type": "contains",
            })
    for agent in agents:
        nodes.append({
            "id": agent.agent_key,
            "type": "agent",
            "label": agent.display_name,
            "role": agent.role_title,
            "department_key": agent.department_key,
            "manager_agent_key": agent.manager_agent_key,
            "availability": agent.availability,
            "status": agent.status,
            "runtime_key": agent.preferred_runtime_key,
            "runtime_name": runtime_map.get(agent.preferred_runtime_key, agent.preferred_runtime_key),
            "reliability_score": agent.reliability_score,
            "utilization": round(agent.current_workload / agent.max_concurrency, 4) if agent.max_concurrency else 0.0,
        })
        edges.append({
            "source": agent.department_key,
            "target": agent.agent_key,
            "type": "member",
        })
        if agent.manager_agent_key:
            edges.append({
                "source": agent.manager_agent_key,
                "target": agent.agent_key,
                "type": "reports_to",
            })
    delegations = list(
        db.scalars(
            select(AgentDelegation).where(AgentDelegation.status == "ACTIVE")
        ).all()
    )
    for delegation in delegations:
        edges.append({
            "source": delegation.source_agent_key,
            "target": delegation.target_agent_key,
            "type": "delegates_to",
            "scope": delegation.scope,
            "delegation_key": delegation.delegation_key,
        })
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": registry_stats(db),
        "generated_at": utcnow().isoformat(),
    }


def agent_detail(db: Session, row: RegisteredAgent) -> dict[str, Any]:
    direct_reports = list(
        db.scalars(
            select(RegisteredAgent).where(
                RegisteredAgent.manager_agent_key == row.agent_key
            ).order_by(RegisteredAgent.display_name)
        ).all()
    )
    delegations_out = list(
        db.scalars(
            select(AgentDelegation).where(
                AgentDelegation.source_agent_key == row.agent_key,
                AgentDelegation.status == "ACTIVE",
            )
        ).all()
    )
    delegations_in = list(
        db.scalars(
            select(AgentDelegation).where(
                AgentDelegation.target_agent_key == row.agent_key,
                AgentDelegation.status == "ACTIVE",
            )
        ).all()
    )
    manager = None
    if row.manager_agent_key:
        manager_row = db.scalar(
            select(RegisteredAgent).where(
                RegisteredAgent.agent_key == row.manager_agent_key
            )
        )
        if manager_row:
            manager = {
                "key": manager_row.agent_key,
                "name": manager_row.display_name,
                "role": manager_row.role_title,
            }
    return {
        **agent_view(row),
        "manager": manager,
        "direct_reports": [
            {"key": item.agent_key, "name": item.display_name, "role": item.role_title}
            for item in direct_reports
        ],
        "delegations_out": [delegation_view(item) for item in delegations_out],
        "delegations_in": [delegation_view(item) for item in delegations_in],
    }


def reliability_from_runs(successful: int, failed: int, prior: float = 0.90) -> float:
    total = max(0, successful) + max(0, failed)
    if total <= 0:
        return min(1.0, max(0.0, prior))
    empirical = successful / total
    weight = min(0.90, total / 50)
    score = prior * (1 - weight) + empirical * weight
    return round(min(1.0, max(0.0, score)), 4)


def create_delegation(
    db: Session,
    *,
    source_agent_key: str,
    target_agent_key: str,
    scope: list[str],
    reason: str,
    ends_at: Any,
    created_by: str,
) -> AgentDelegation:
    source = db.scalar(
        select(RegisteredAgent).where(RegisteredAgent.agent_key == source_agent_key)
    )
    target = db.scalar(
        select(RegisteredAgent).where(RegisteredAgent.agent_key == target_agent_key)
    )
    if source is None or target is None:
        raise ValueError("Delegation source and target agents must exist")
    if source.agent_key == target.agent_key:
        raise ValueError("An agent cannot delegate to itself")
    if target.status != "ACTIVE":
        raise ValueError("Delegation target must be active")
    now = utcnow()
    row = AgentDelegation(
        delegation_key=f"DEL-{uuid4().hex[:14].upper()}",
        source_agent_key=source.agent_key,
        target_agent_key=target.agent_key,
        scope=sorted(set(scope)),
        reason=reason,
        status="ACTIVE",
        starts_at=now,
        ends_at=ends_at,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row
