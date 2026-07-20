from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

import collaboration_service
import governance_service
import phase4_app
import phase5_app
import phase7_runtime  # noqa: F401 — install Phase 1–7 and hardened registry runtime
from collaboration_models import (
    CollaborationTask,
    TERMINAL_TASK_STATUSES,
    aware,
    task_view,
)
from collaboration_service import collaboration_event, create_message
from governance_models import GovernanceRole
from main import (
    Mission,
    MissionEvent,
    SessionLocal,
    app,
    bounded_payload,
    db_session,
    redis_client,
    utcnow,
)
from phase6_app import require_governance
from scheduler_models import (
    RoutedTaskCreate,
    RoutingDecision,
    RoutingSimulation,
    SchedulerPolicy,
    SchedulerPolicyUpdate,
    decision_view,
    policy_view,
)
from scheduler_service import (
    SCHEDULER_BATCH,
    SCHEDULER_ENABLED,
    SCHEDULER_INTERVAL,
    active_policy,
    prepare_failover,
    route_task,
    routing_request_snapshot,
    runtime_pool,
    scheduler_stats,
    scheduler_tick,
    scheduler_worker,
    score_candidates,
    seed_scheduler,
    task_needs_route,
)

app.version = "0.9.0"
_scheduler_worker_task: asyncio.Task[None] | None = None
_original_dispatch_task = collaboration_service.dispatch_task


async def routed_dispatch_task(db: Session, task: CollaborationTask) -> None:
    if task.status not in {"QUEUED", "REVISION"}:
        return await _original_dispatch_task(db, task)
    if task_needs_route(task):
        decision = route_task(db, task, actor="service:scheduler")
        if decision is None:
            return
        if decision.status != "SELECTED":
            db.commit()
            return
    await _original_dispatch_task(db, task)
    if task.status == "BLOCKED" and task.dispatch_key:
        reason = str((task.result or {}).get("error") or "Runtime dispatch failed")
        if prepare_failover(db, task, reason):
            db.commit()


# Phase 4 imported dispatch_task by value, so patch both the module and the API module.
collaboration_service.dispatch_task = routed_dispatch_task
phase4_app.dispatch_task = routed_dispatch_task
phase5_app.dispatch_task = routed_dispatch_task


_PHASE8_ROUTE_RULES = [
    ("POST", re.compile(r"^/api/missions/[^/]+/routed-tasks$"), "scheduler:route"),
    ("POST", re.compile(r"^/api/scheduler/simulate$"), "scheduler:read"),
    ("POST", re.compile(r"^/api/scheduler/tasks/[^/]+/route$"), "scheduler:route"),
    ("POST", re.compile(r"^/api/scheduler/tick$"), "scheduler:route"),
    ("PATCH", re.compile(r"^/api/scheduler/policies/[^/]+$"), "scheduler:policy:write"),
]
for rule in reversed(_PHASE8_ROUTE_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)


def ensure_scheduler_permissions(db: Session) -> None:
    additions = {
        "role:executive": {"scheduler:read", "scheduler:route", "scheduler:policy:write"},
        "role:manager": {"scheduler:read", "scheduler:route"},
        "role:operator": {"scheduler:read", "scheduler:route"},
        "role:auditor": {"scheduler:read"},
        "role:agent": {"scheduler:read"},
        "role:service": {"scheduler:read", "scheduler:route"},
        "role:runtime": {"scheduler:read"},
    }
    changed = False
    for role_key, permissions in additions.items():
        role = db.scalar(
            select(GovernanceRole).where(GovernanceRole.role_key == role_key)
        )
        if role is None:
            continue
        merged = sorted(set(role.permissions or []) | permissions)
        if merged != role.permissions:
            role.permissions = merged
            role.updated_at = utcnow()
            changed = True
    if changed:
        db.commit()


@app.on_event("startup")
async def start_scheduler() -> None:
    global _scheduler_worker_task
    with SessionLocal() as db:
        ensure_scheduler_permissions(db)
        seed_scheduler(db)
    if not SCHEDULER_ENABLED:
        redis_client.hset("beezaoffice:scheduler-worker", mapping={"status": "disabled"})
        return
    if _scheduler_worker_task is None or _scheduler_worker_task.done():
        _scheduler_worker_task = asyncio.create_task(
            scheduler_worker(), name="beeza-scheduler-worker"
        )


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    global _scheduler_worker_task
    if _scheduler_worker_task is None:
        return
    _scheduler_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _scheduler_worker_task
    _scheduler_worker_task = None


@app.get("/api/scheduler/status")
def read_scheduler_status(
    _: str = Depends(require_governance("scheduler:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    worker = redis_client.hgetall("beezaoffice:scheduler-worker")
    return {
        "enabled": SCHEDULER_ENABLED,
        "worker": {
            "status": worker.get("status", "starting"),
            "last_tick_at": worker.get("last_tick_at"),
            "last_routed": int(worker.get("last_routed", "0") or 0),
            "last_waiting": int(worker.get("last_waiting", "0") or 0),
            "last_blocked": int(worker.get("last_blocked", "0") or 0),
            "interval_seconds": float(
                worker.get("interval_seconds", str(SCHEDULER_INTERVAL))
            ),
            "last_error": worker.get("last_error"),
        },
        "batch_size": SCHEDULER_BATCH,
        "stats": scheduler_stats(db),
    }


@app.post("/api/scheduler/tick")
async def run_scheduler_tick(
    _: str = Depends(require_governance("scheduler:route")),
) -> dict[str, Any]:
    return {"ok": True, **(await scheduler_tick())}


@app.get("/api/scheduler/runtime-pool")
def read_runtime_pool(
    _: str = Depends(require_governance("scheduler:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    return runtime_pool(db)


@app.get("/api/scheduler/policies")
def list_scheduler_policies(
    _: str = Depends(require_governance("scheduler:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SchedulerPolicy).order_by(SchedulerPolicy.name)
    ).all()
    return [policy_view(row) for row in rows]


@app.patch("/api/scheduler/policies/{policy_key}")
def update_scheduler_policy(
    policy_key: str,
    payload: SchedulerPolicyUpdate,
    actor: str = Depends(require_governance("scheduler:policy:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(SchedulerPolicy).where(SchedulerPolicy.policy_key == policy_key)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scheduler policy not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field in {"weights", "runtime_limits", "runtime_cost_per_1k_tokens", "settings"} and value is not None:
            value = {**(getattr(row, field) or {}), **value}
        setattr(row, field, value)
    row.settings = {**(row.settings or {}), "updated_by": actor}
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return policy_view(row)


@app.get("/api/scheduler/decisions")
def list_routing_decisions(
    mission_key: str | None = Query(default=None, max_length=80),
    task_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("scheduler:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(RoutingDecision)
    if mission_key:
        statement = statement.where(RoutingDecision.mission_key == mission_key)
    if task_key:
        statement = statement.where(RoutingDecision.task_key == task_key)
    if status:
        statement = statement.where(RoutingDecision.status == status.upper())
    rows = db.scalars(
        statement.order_by(RoutingDecision.created_at.desc()).limit(limit)
    ).all()
    return [decision_view(row) for row in rows]


@app.post("/api/scheduler/simulate")
def simulate_route(
    payload: RoutingSimulation,
    actor: str = Depends(require_governance("scheduler:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    policy = active_policy(db)
    request = payload.model_dump(mode="python")
    request.update({
        "routing_mode": "AUTO",
        "requested_target_identity": "agent:auto",
        "requested_runtime_key": "auto",
    })
    candidates = score_candidates(db, request, policy)
    selected = next((item for item in candidates if item["accepted"]), None)
    return {
        "simulated_by": actor,
        "policy": policy_view(policy),
        "request": routing_request_snapshot(request),
        "selected": selected,
        "candidates": candidates,
    }


@app.post(
    "/api/missions/{mission_key}/routed-tasks",
    status_code=201,
)
async def create_routed_task(
    mission_key: str,
    payload: RoutedTaskCreate,
    actor: str = Depends(require_governance("scheduler:route")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == mission_key)
    )
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    dependencies = list(dict.fromkeys(payload.depends_on))
    if dependencies:
        known = set(
            db.scalars(
                select(CollaborationTask.task_key).where(
                    CollaborationTask.task_key.in_(dependencies),
                    CollaborationTask.mission_key == mission_key,
                )
            ).all()
        )
        unknown = [key for key in dependencies if key not in known]
        if unknown:
            raise HTTPException(
                status_code=409,
                detail=f"Unknown dependencies: {', '.join(unknown)}",
            )
    now = utcnow()
    routing_context = {
        "routing_mode": payload.routing_mode,
        "required_skills": sorted(set(payload.required_skills)),
        "required_capabilities": sorted(set(payload.required_capabilities)),
        "required_tools": sorted(set(payload.required_tools)),
        "required_clearance": payload.required_clearance,
        "preferred_department": payload.preferred_department,
        "preferred_runtime_key": payload.preferred_runtime_key,
        "maximum_cost_usd": payload.maximum_cost_usd,
        "estimated_tokens": payload.estimated_tokens,
        "strict_skills": payload.strict_skills,
        "allow_overflow": payload.allow_overflow,
        "routing": {
            "mode": payload.routing_mode,
            "status": "QUEUED",
            "attempts": 0,
        },
    }
    task = CollaborationTask(
        task_key=f"TASK-{uuid4().hex[:12].upper()}",
        mission_key=mission_key,
        parent_task_key=None,
        title=payload.title,
        objective=payload.objective,
        source_identity=payload.source_identity,
        target_identity="agent:auto",
        target_runtime_key="auto",
        status="WAITING_DEPENDENCY" if dependencies else "QUEUED",
        priority=payload.priority,
        review_policy=payload.review_policy,
        auto_dispatch=payload.auto_dispatch,
        depends_on=dependencies,
        inputs=bounded_payload(payload.inputs),
        expected_outputs=payload.expected_outputs,
        acceptance_criteria=payload.acceptance_criteria,
        context=bounded_payload({**payload.context, **routing_context}),
        result={},
        dispatch_key=None,
        attempts=0,
        follow_up_count=0,
        last_progress_at=now,
        next_follow_up_at=None,
        deadline_at=aware(payload.deadline_at),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    create_message(
        db,
        mission_key=mission_key,
        task_key=task.task_key,
        message_type="HANDOFF",
        source_identity=payload.source_identity,
        target_identity="service:scheduler",
        subject=f"Route work · {payload.title}",
        body=payload.objective,
        payload={
            "required_skills": payload.required_skills,
            "required_capabilities": payload.required_capabilities,
            "required_tools": payload.required_tools,
            "required_clearance": payload.required_clearance,
            "preferred_runtime_key": payload.preferred_runtime_key,
            "maximum_cost_usd": payload.maximum_cost_usd,
            "routing_mode": payload.routing_mode,
        },
        status="DELIVERED",
        reply_required=True,
        due_at=task.deadline_at,
    )
    collaboration_event(
        db,
        task,
        "ROUTED_TASK_CREATED",
        actor,
        f"Created intelligent routing request {task.task_key}.",
        routing_context,
    )
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor=actor[:80],
            event_type="ROUTED_TASK_CREATED",
            message=f"{task.task_key}: {task.title} queued for intelligent routing."[:800],
            created_at=now,
        )
    )
    mission.status = "EXECUTING"
    mission.waiting_for = f"Scheduler routing {task.task_key}"
    db.commit()
    db.refresh(task)
    if task.auto_dispatch and task.status == "QUEUED":
        await routed_dispatch_task(db, task)
        db.refresh(task)
    return task_view(task)


@app.post("/api/scheduler/tasks/{task_key}/route")
def reroute_task(
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
    context = dict(task.context or {})
    routing = dict(context.get("routing") or {})
    excluded_agents = list(context.get("excluded_agents") or [])
    excluded_runtimes = list(context.get("excluded_runtimes") or [])
    if routing.get("selected_agent_key"):
        excluded_agents.append(routing["selected_agent_key"])
    if routing.get("selected_runtime_key"):
        excluded_runtimes.append(routing["selected_runtime_key"])
    routing.update({
        "mode": str(context.get("routing_mode") or routing.get("mode") or "FAILOVER").upper(),
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
