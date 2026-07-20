from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask
from collaboration_service import collaboration_event, create_message
from main import RuntimeConnector, RuntimeDispatch, SessionLocal, redis_client, utcnow
from registry_models import RegisteredAgent
from registry_service import reconcile_workloads
from scheduler_models import RoutingDecision, SchedulerPolicy, decision_view, policy_view

SCHEDULER_ENABLED = os.getenv("BEEZA_SCHEDULER_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
SCHEDULER_INTERVAL = max(2.0, float(os.getenv("BEEZA_SCHEDULER_INTERVAL_SECONDS", "3")))
SCHEDULER_BATCH = max(1, min(500, int(os.getenv("BEEZA_SCHEDULER_BATCH_SIZE", "100"))))
FAILOVER_ATTEMPTS = max(1, min(20, int(os.getenv("BEEZA_SCHEDULER_FAILOVER_ATTEMPTS", "3"))))
ACTIVE_RUNTIME_STATUSES = {"DISPATCHING", "STARTED", "RUNNING", "QUEUED", "WAITING_APPROVAL", "STOPPING"}
AUTO_IDENTITIES = {"auto", "agent:auto", "runtime:auto", "scheduler:auto"}
CLEARANCE_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}

DEFAULT_WEIGHTS = {
    "skill": 0.28,
    "reliability": 0.20,
    "capacity": 0.18,
    "runtime": 0.14,
    "cost": 0.10,
    "deadline": 0.06,
    "affinity": 0.04,
}
DEFAULT_RUNTIME_LIMITS = {
    "openclaw": 25,
    "cherryagent": 50,
    "hermes": 25,
    "thclaws": 25,
}
DEFAULT_RUNTIME_COSTS = {
    "openclaw": 0.006,
    "cherryagent": 0.003,
    "hermes": 0.012,
    "thclaws": 0.002,
}


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return aware(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return aware(parsed)
        except ValueError:
            return None
    return None


def normalized(values: list[str] | None) -> set[str]:
    return {str(item).strip().casefold() for item in values or [] if str(item).strip()}


def seed_scheduler(db: Session) -> SchedulerPolicy:
    row = db.scalar(
        select(SchedulerPolicy).where(SchedulerPolicy.policy_key == "policy:balanced")
    )
    if row is not None:
        return row
    now = utcnow()
    row = SchedulerPolicy(
        policy_key="policy:balanced",
        name="Balanced Agent Router",
        enabled=True,
        weights=DEFAULT_WEIGHTS,
        runtime_limits=DEFAULT_RUNTIME_LIMITS,
        runtime_cost_per_1k_tokens=DEFAULT_RUNTIME_COSTS,
        default_token_estimate=4000,
        minimum_score=0.35,
        minimum_skill_coverage=0.50,
        max_route_attempts=5,
        retry_seconds=30,
        settings={
            "prefer_online_runtime": True,
            "prefer_local_runtime": True,
            "strict_clearance": True,
            "candidate_limit": 50,
        },
        created_by="system:phase8",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def active_policy(db: Session) -> SchedulerPolicy:
    row = db.scalar(
        select(SchedulerPolicy)
        .where(SchedulerPolicy.enabled.is_(True))
        .order_by(SchedulerPolicy.id)
    )
    return row or seed_scheduler(db)


def runtime_pool(db: Session, policy: SchedulerPolicy | None = None) -> list[dict[str, Any]]:
    policy = policy or active_policy(db)
    runtimes = list(db.scalars(select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)).all())
    active_counts = Counter(
        db.scalars(
            select(RuntimeDispatch.runtime_key).where(
                RuntimeDispatch.status.in_(ACTIVE_RUNTIME_STATUSES)
            )
        ).all()
    )
    result: list[dict[str, Any]] = []
    for runtime in runtimes:
        limit = max(1, int((policy.runtime_limits or {}).get(runtime.runtime_key, 10)))
        active = int(active_counts.get(runtime.runtime_key, 0))
        cost = float((policy.runtime_cost_per_1k_tokens or {}).get(runtime.runtime_key, 0.0))
        result.append({
            "runtime_key": runtime.runtime_key,
            "name": runtime.display_name,
            "platform": runtime.platform,
            "configured": bool(runtime.base_url),
            "status": runtime.status,
            "model": runtime.model,
            "capabilities": runtime.capabilities,
            "active_dispatches": active,
            "capacity_limit": limit,
            "available_slots": max(0, limit - active),
            "utilization": round(active / limit, 4),
            "latency_ms": runtime.last_latency_ms,
            "last_error": runtime.last_error,
            "cost_per_1k_tokens_usd": cost,
        })
    return result


def request_from_task(task: CollaborationTask, policy: SchedulerPolicy) -> dict[str, Any]:
    context = dict(task.context or {})
    routing = dict(context.get("routing") or {})
    return {
        "objective": task.objective,
        "priority": task.priority,
        "required_skills": context.get("required_skills") or routing.get("required_skills") or [],
        "required_capabilities": context.get("required_capabilities") or routing.get("required_capabilities") or [],
        "required_tools": context.get("required_tools") or routing.get("required_tools") or [],
        "required_clearance": str(context.get("required_clearance") or routing.get("required_clearance") or "INTERNAL").upper(),
        "preferred_department": context.get("preferred_department") or routing.get("preferred_department"),
        "preferred_runtime_key": context.get("preferred_runtime_key") or routing.get("preferred_runtime_key"),
        "maximum_cost_usd": context.get("maximum_cost_usd") if context.get("maximum_cost_usd") is not None else routing.get("maximum_cost_usd"),
        "estimated_tokens": int(context.get("estimated_tokens") or routing.get("estimated_tokens") or policy.default_token_estimate),
        "strict_skills": bool(context.get("strict_skills", routing.get("strict_skills", False))),
        "allow_overflow": bool(context.get("allow_overflow", routing.get("allow_overflow", False))),
        "deadline_at": aware(task.deadline_at),
        "excluded_agents": list(dict.fromkeys(context.get("excluded_agents") or routing.get("excluded_agents") or [])),
        "excluded_runtimes": list(dict.fromkeys(context.get("excluded_runtimes") or routing.get("excluded_runtimes") or [])),
        "requested_target_identity": task.target_identity,
        "requested_runtime_key": task.target_runtime_key,
        "routing_mode": str(context.get("routing_mode") or routing.get("mode") or "AUTO").upper(),
    }


def coverage(required: set[str], available: set[str]) -> float:
    if not required:
        return 1.0
    return len(required & available) / len(required)


def runtime_health(status: str, latency_ms: float | None) -> tuple[float, float]:
    status_scores = {
        "ONLINE": 1.0,
        "UNKNOWN": 0.70,
        "DEGRADED": 0.45,
        "OFFLINE": 0.0,
        "UNCONFIGURED": 0.0,
    }
    health = status_scores.get(str(status or "UNKNOWN").upper(), 0.55)
    latency = max(0.0, float(latency_ms or 500.0))
    latency_score = 1.0 / (1.0 + latency / 750.0)
    return health, latency_score


def estimate_cost(policy: SchedulerPolicy, runtime_key: str, tokens: int) -> float:
    rate = float((policy.runtime_cost_per_1k_tokens or {}).get(runtime_key, 0.0))
    return round(rate * max(1, tokens) / 1000.0, 6)


def normalized_weights(policy: SchedulerPolicy) -> dict[str, float]:
    weights = {**DEFAULT_WEIGHTS, **(policy.weights or {})}
    positive = {key: max(0.0, float(value)) for key, value in weights.items()}
    total = sum(positive.values()) or 1.0
    return {key: value / total for key, value in positive.items()}


def deadline_component(deadline_at: datetime | None, capacity_score: float, latency_score: float) -> tuple[float, float]:
    if deadline_at is None:
        return 0.50, 0.0
    remaining = max(0.0, (aware(deadline_at) - utcnow()).total_seconds())
    urgency = 1.0 - min(1.0, remaining / 86400.0)
    score = (capacity_score * 0.60 + latency_score * 0.40) * urgency + 0.50 * (1.0 - urgency)
    return min(1.0, max(0.0, score)), urgency


def score_candidates(
    db: Session,
    request: dict[str, Any],
    policy: SchedulerPolicy | None = None,
) -> list[dict[str, Any]]:
    policy = policy or active_policy(db)
    weights = normalized_weights(policy)
    agents = list(db.scalars(select(RegisteredAgent).order_by(RegisteredAgent.agent_key)).all())
    runtimes = {
        row.runtime_key: row
        for row in db.scalars(select(RuntimeConnector)).all()
    }
    pool = {item["runtime_key"]: item for item in runtime_pool(db, policy)}
    required_skills = normalized(request.get("required_skills"))
    required_capabilities = normalized(request.get("required_capabilities"))
    required_tools = normalized(request.get("required_tools"))
    required_clearance = str(request.get("required_clearance") or "INTERNAL").upper()
    required_rank = CLEARANCE_RANK.get(required_clearance, 1)
    excluded_agents = normalized(request.get("excluded_agents"))
    excluded_runtimes = normalized(request.get("excluded_runtimes"))
    preferred_department = str(request.get("preferred_department") or "").strip()
    preferred_runtime = str(request.get("preferred_runtime_key") or "").strip()
    maximum_cost = request.get("maximum_cost_usd")
    estimated_tokens = int(request.get("estimated_tokens") or policy.default_token_estimate)
    allow_overflow = bool(request.get("allow_overflow"))
    strict_skills = bool(request.get("strict_skills"))
    requested_target = str(request.get("requested_target_identity") or "").removeprefix("agent:").casefold()
    candidates: list[dict[str, Any]] = []

    for agent in agents:
        reasons: list[str] = []
        rejected: list[str] = []
        runtime = runtimes.get(agent.preferred_runtime_key)
        runtime_state = pool.get(agent.preferred_runtime_key, {})
        if agent.agent_key.casefold() in excluded_agents or agent.identity_key.casefold() in excluded_agents:
            rejected.append("agent excluded by prior route or operator")
        if agent.status != "ACTIVE":
            rejected.append(f"agent status {agent.status}")
        if agent.availability in {"OFFLINE", "MAINTENANCE"}:
            rejected.append(f"agent availability {agent.availability}")
        if CLEARANCE_RANK.get(agent.data_clearance, 0) < required_rank:
            rejected.append(f"clearance {agent.data_clearance} below {required_clearance}")
        if runtime is None:
            rejected.append("preferred runtime is missing")
        elif not runtime.base_url:
            rejected.append("preferred runtime is not configured")
        if agent.preferred_runtime_key.casefold() in excluded_runtimes:
            rejected.append("runtime excluded by prior route or operator")
        if runtime_state and runtime_state.get("available_slots", 0) <= 0 and not allow_overflow:
            rejected.append("runtime pool is at capacity")
        available_capacity = max(0, agent.max_concurrency - agent.current_workload)
        if available_capacity <= 0 and not allow_overflow:
            rejected.append("agent concurrency is full")

        skills = normalized(agent.skills)
        capabilities = normalized(agent.capabilities)
        tools = normalized(agent.allowed_tools)
        skill_coverage = coverage(required_skills, skills)
        capability_coverage = coverage(required_capabilities, capabilities)
        tool_coverage = coverage(required_tools, tools)
        if required_skills and skill_coverage < policy.minimum_skill_coverage:
            rejected.append(
                f"skill coverage {skill_coverage:.2f} below {policy.minimum_skill_coverage:.2f}"
            )
        if strict_skills and (
            skill_coverage < 1.0 or capability_coverage < 1.0 or tool_coverage < 1.0
        ):
            rejected.append("strict skill/capability/tool match failed")

        cost = estimate_cost(policy, agent.preferred_runtime_key, estimated_tokens)
        if maximum_cost is not None and cost > float(maximum_cost):
            rejected.append(f"estimated cost ${cost:.4f} exceeds ceiling")

        skill_score = skill_coverage * 0.60 + capability_coverage * 0.25 + tool_coverage * 0.15
        reliability_score = min(1.0, max(0.0, float(agent.reliability_score)))
        capacity_score = min(1.0, available_capacity / max(1, agent.max_concurrency))
        health_score, latency_score = runtime_health(
            runtime.status if runtime else "OFFLINE",
            runtime.last_latency_ms if runtime else None,
        )
        runtime_score = health_score * 0.60 + latency_score * 0.40
        if maximum_cost is not None and float(maximum_cost) > 0:
            cost_score = max(0.0, 1.0 - cost / float(maximum_cost))
        else:
            cost_score = 1.0 / (1.0 + cost * 25.0)
        deadline_score, urgency = deadline_component(
            request.get("deadline_at"), capacity_score, latency_score
        )
        affinity = 0.0
        if preferred_department and agent.department_key == preferred_department:
            affinity += 0.45
            reasons.append("preferred department")
        if preferred_runtime and agent.preferred_runtime_key == preferred_runtime:
            affinity += 0.35
            reasons.append("preferred runtime")
        if requested_target and agent.agent_key.casefold() == requested_target:
            affinity += 0.20
            reasons.append("requested agent")
        affinity = min(1.0, affinity)
        components = {
            "skill": round(skill_score, 4),
            "reliability": round(reliability_score, 4),
            "capacity": round(capacity_score, 4),
            "runtime": round(runtime_score, 4),
            "cost": round(cost_score, 4),
            "deadline": round(deadline_score, 4),
            "affinity": round(affinity, 4),
        }
        score = sum(components.get(key, 0.0) * weight for key, weight in weights.items())
        if urgency > 0.75:
            reasons.append("deadline urgency favors capacity and latency")
        if available_capacity > 0:
            reasons.append(f"{available_capacity} agent slots available")
        if runtime_state.get("available_slots", 0) > 0:
            reasons.append(f"{runtime_state['available_slots']} runtime slots available")
        if skill_coverage >= 1.0 and required_skills:
            reasons.append("all required skills matched")
        candidate = {
            "agent_key": agent.agent_key,
            "identity_key": agent.identity_key,
            "name": agent.display_name,
            "role": agent.role_title,
            "department_key": agent.department_key,
            "runtime_key": agent.preferred_runtime_key,
            "runtime_name": runtime.display_name if runtime else agent.preferred_runtime_key,
            "model": agent.preferred_model or (runtime.model if runtime else ""),
            "score": round(score, 6),
            "accepted": not rejected and score >= policy.minimum_score,
            "components": components,
            "skill_coverage": round(skill_coverage, 4),
            "capability_coverage": round(capability_coverage, 4),
            "tool_coverage": round(tool_coverage, 4),
            "available_capacity": available_capacity,
            "runtime_available_slots": runtime_state.get("available_slots", 0),
            "runtime_latency_ms": runtime.last_latency_ms if runtime else None,
            "estimated_cost_usd": cost,
            "reasons": reasons,
            "rejections": rejected,
        }
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            bool(item["accepted"]),
            float(item["score"]),
            float(item["components"]["reliability"]),
            item["agent_key"],
        ),
        reverse=True,
    )
    limit = max(1, min(200, int((policy.settings or {}).get("candidate_limit", 50))))
    return candidates[:limit]


def task_needs_route(task: CollaborationTask) -> bool:
    context = dict(task.context or {})
    routing = dict(context.get("routing") or {})
    mode = str(context.get("routing_mode") or routing.get("mode") or "FIXED").upper()
    automatic_target = str(task.target_identity or "").casefold() in AUTO_IDENTITIES
    automatic_runtime = str(task.target_runtime_key or "").casefold() == "auto"
    routing_status = str(routing.get("status") or context.get("routing_status") or "").upper()
    force = bool(context.get("force_reroute") or routing.get("force_reroute"))
    return automatic_target or automatic_runtime or force or (
        mode in {"AUTO", "BEST", "FAILOVER"} and routing_status != "SELECTED"
    )


def routing_request_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(request)
    deadline = snapshot.get("deadline_at")
    if isinstance(deadline, datetime):
        snapshot["deadline_at"] = deadline.isoformat()
    return snapshot


def route_task(
    db: Session,
    task: CollaborationTask,
    *,
    actor: str = "service:scheduler",
    force: bool = False,
) -> RoutingDecision | None:
    lock_key = f"beezaoffice:scheduler-route:{task.task_key}"
    if not redis_client.set(lock_key, "1", nx=True, ex=30):
        return None
    try:
        policy = active_policy(db)
        context = dict(task.context or {})
        routing = dict(context.get("routing") or {})
        next_route_at = parse_time(routing.get("next_route_at"))
        if not force and next_route_at and next_route_at > utcnow():
            return None
        attempt = int(routing.get("attempts") or 0) + 1
        request = request_from_task(task, policy)
        candidates = score_candidates(db, request, policy)
        selected = next((item for item in candidates if item["accepted"]), None)
        now = utcnow()
        decision = RoutingDecision(
            decision_key=f"ROUTE-{uuid4().hex[:14].upper()}",
            mission_key=task.mission_key,
            task_key=task.task_key,
            policy_key=policy.policy_key,
            status="SELECTED" if selected else (
                "NO_ROUTE" if attempt >= policy.max_route_attempts else "WAITING"
            ),
            attempt=attempt,
            selected_agent_key=selected["agent_key"] if selected else None,
            selected_runtime_key=selected["runtime_key"] if selected else None,
            selected_model=selected["model"] if selected else None,
            selected_score=selected["score"] if selected else None,
            requested=routing_request_snapshot(request),
            candidates=candidates,
            reason=(
                f"Selected {selected['name']} on {selected['runtime_name']} with score {selected['score']:.3f}."
                if selected
                else "No eligible candidate currently satisfies skills, clearance, cost and capacity constraints."
            ),
            created_by=actor,
            created_at=now,
        )
        db.add(decision)
        db.flush()
        routing.update({
            "mode": request["routing_mode"],
            "status": decision.status,
            "decision_key": decision.decision_key,
            "policy_key": policy.policy_key,
            "attempts": attempt,
            "requested": decision.requested,
            "selected_agent_key": decision.selected_agent_key,
            "selected_runtime_key": decision.selected_runtime_key,
            "selected_model": decision.selected_model,
            "selected_score": decision.selected_score,
            "routed_at": now.isoformat() if selected else None,
            "next_route_at": None if selected else (
                now + timedelta(seconds=policy.retry_seconds)
            ).isoformat(),
        })
        context["routing"] = routing
        context["routing_mode"] = request["routing_mode"]
        context.pop("force_reroute", None)
        task.context = context
        task.updated_at = now

        if selected:
            previous_target = task.target_identity
            task.target_identity = selected["identity_key"]
            task.target_runtime_key = selected["runtime_key"]
            agent = db.scalar(
                select(RegisteredAgent).where(
                    RegisteredAgent.agent_key == selected["agent_key"]
                )
            )
            if agent and previous_target.casefold() in AUTO_IDENTITIES:
                agent.current_workload = min(
                    agent.max_concurrency * 10,
                    agent.current_workload + 1,
                )
                agent.availability = "BUSY"
                agent.updated_at = now
            create_message(
                db,
                mission_key=task.mission_key,
                task_key=task.task_key,
                message_type="ASSIGN",
                source_identity=actor,
                target_identity=task.target_identity,
                subject=f"Intelligent route · {task.title}",
                body=decision.reason,
                payload={
                    "routing_decision_key": decision.decision_key,
                    "runtime_key": selected["runtime_key"],
                    "model": selected["model"],
                    "score": selected["score"],
                    "components": selected["components"],
                },
                status="DELIVERED",
                reply_required=True,
                due_at=task.deadline_at,
            )
            collaboration_event(
                db,
                task,
                "TASK_ROUTED",
                actor,
                decision.reason,
                {
                    "routing_decision_key": decision.decision_key,
                    "agent_key": selected["agent_key"],
                    "runtime_key": selected["runtime_key"],
                    "model": selected["model"],
                    "score": selected["score"],
                    "components": selected["components"],
                    "estimated_cost_usd": selected["estimated_cost_usd"],
                },
            )
        elif attempt >= policy.max_route_attempts:
            task.status = "BLOCKED"
            task.result = {
                **(task.result or {}),
                "error": decision.reason,
                "routing_decision_key": decision.decision_key,
                "route_attempts": attempt,
            }
            collaboration_event(
                db,
                task,
                "ROUTING_FAILED",
                actor,
                f"Routing exhausted after {attempt} attempts.",
                {"routing_decision_key": decision.decision_key, "candidates": candidates[:10]},
                "ERROR",
            )
        else:
            collaboration_event(
                db,
                task,
                "ROUTING_WAITING",
                actor,
                f"No eligible route; retry {attempt}/{policy.max_route_attempts} scheduled.",
                {
                    "routing_decision_key": decision.decision_key,
                    "next_route_at": routing["next_route_at"],
                    "candidates": candidates[:10],
                },
                "WARNING",
            )
        return decision
    finally:
        redis_client.delete(lock_key)


def prepare_failover(db: Session, task: CollaborationTask, reason: str) -> bool:
    context = dict(task.context or {})
    routing = dict(context.get("routing") or {})
    mode = str(context.get("routing_mode") or routing.get("mode") or "FIXED").upper()
    failovers = int(routing.get("failovers") or 0)
    if mode not in {"AUTO", "FAILOVER", "BEST"} or failovers >= FAILOVER_ATTEMPTS:
        return False
    selected_agent = routing.get("selected_agent_key")
    selected_runtime = routing.get("selected_runtime_key")
    excluded_agents = list(dict.fromkeys([
        *(context.get("excluded_agents") or []),
        *([selected_agent] if selected_agent else []),
    ]))
    excluded_runtimes = list(dict.fromkeys([
        *(context.get("excluded_runtimes") or []),
        *([selected_runtime] if selected_runtime else []),
    ]))
    routing.update({
        "status": "WAITING",
        "failovers": failovers + 1,
        "last_failure": reason[:1000],
        "next_route_at": utcnow().isoformat(),
        "selected_agent_key": None,
        "selected_runtime_key": None,
        "selected_model": None,
        "selected_score": None,
    })
    context.update({
        "routing": routing,
        "excluded_agents": excluded_agents,
        "excluded_runtimes": excluded_runtimes,
        "force_reroute": True,
    })
    task.context = context
    task.target_identity = "agent:auto"
    task.target_runtime_key = "auto"
    task.dispatch_key = None
    task.status = "QUEUED"
    task.next_follow_up_at = None
    task.updated_at = utcnow()
    collaboration_event(
        db,
        task,
        "ROUTING_FAILOVER_QUEUED",
        "service:scheduler",
        f"Dispatch failed; queued failover {failovers + 1}/{FAILOVER_ATTEMPTS}.",
        {
            "reason": reason[:1000],
            "excluded_agents": excluded_agents,
            "excluded_runtimes": excluded_runtimes,
        },
        "WARNING",
    )
    return True


async def scheduler_tick() -> dict[str, int]:
    routed = waiting = blocked = 0
    with SessionLocal() as db:
        reconcile_workloads(db)
        tasks = list(
            db.scalars(
                select(CollaborationTask)
                .where(CollaborationTask.status.in_(["QUEUED", "REVISION"]))
                .order_by(CollaborationTask.updated_at)
                .limit(SCHEDULER_BATCH)
            ).all()
        )
        for task in tasks:
            if not task_needs_route(task):
                continue
            decision = route_task(db, task)
            if decision is None:
                continue
            if decision.status == "SELECTED":
                routed += 1
            elif decision.status == "WAITING":
                waiting += 1
            else:
                blocked += 1
        db.commit()
    return {"routed": routed, "waiting": waiting, "blocked": blocked}


async def scheduler_worker() -> None:
    while True:
        try:
            result = await scheduler_tick()
            redis_client.hset(
                "beezaoffice:scheduler-worker",
                mapping={
                    "status": "online",
                    "last_tick_at": utcnow().isoformat(),
                    "last_routed": str(result["routed"]),
                    "last_waiting": str(result["waiting"]),
                    "last_blocked": str(result["blocked"]),
                    "interval_seconds": str(SCHEDULER_INTERVAL),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset(
                "beezaoffice:scheduler-worker",
                mapping={
                    "status": "degraded",
                    "last_tick_at": utcnow().isoformat(),
                    "last_error": str(exc)[:500],
                },
            )
        await asyncio.sleep(SCHEDULER_INTERVAL)


def scheduler_stats(db: Session) -> dict[str, Any]:
    policy = active_policy(db)
    decisions = list(
        db.scalars(
            select(RoutingDecision)
            .order_by(RoutingDecision.created_at.desc())
            .limit(1000)
        ).all()
    )
    tasks = list(
        db.scalars(
            select(CollaborationTask)
            .where(CollaborationTask.status.not_in(["COMPLETED", "FAILED", "CANCELLED"]))
        ).all()
    )
    pool = runtime_pool(db, policy)
    decision_counts = Counter(item.status for item in decisions)
    auto_tasks = [task for task in tasks if task_needs_route(task)]
    return {
        "policy": policy_view(policy),
        "decisions": dict(sorted(decision_counts.items())),
        "active_tasks": len(tasks),
        "awaiting_route": len(auto_tasks),
        "runtime_capacity": sum(item["capacity_limit"] for item in pool),
        "runtime_active": sum(item["active_dispatches"] for item in pool),
        "runtime_available": sum(item["available_slots"] for item in pool),
        "configured_runtimes": sum(item["configured"] for item in pool),
        "online_runtimes": sum(item["status"] == "ONLINE" for item in pool),
        "average_selected_score": round(
            sum(item.selected_score or 0 for item in decisions if item.status == "SELECTED")
            / max(1, sum(item.status == "SELECTED" for item in decisions)),
            4,
        ),
    }
