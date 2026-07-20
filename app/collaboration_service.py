from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import (
    CollaborationMessage, CollaborationTask, MESSAGE_STATUSES, MESSAGE_TYPES,
    TERMINAL_TASK_STATUSES, aware, iso,
)
from main import (
    Mission, RuntimeConnector, RuntimeDispatch, SessionLocal, bounded_payload,
    dispatch_runtime, redis_client, runtime_config, utcnow,
)
from phase2_app import normalize_remote_status
from phase3_app import RuntimeEvent
from runtime_adapters import RuntimeAdapterError

FOLLOW_UP_SECONDS = max(30, int(os.getenv("BEEZA_COLLAB_FOLLOW_UP_SECONDS", "300")))
MAX_FOLLOW_UPS = max(1, int(os.getenv("BEEZA_COLLAB_MAX_FOLLOW_UPS", "2")))
COLLAB_INTERVAL = max(2.0, float(os.getenv("BEEZA_COLLAB_INTERVAL_SECONDS", "3")))
COLLAB_BATCH = max(1, min(500, int(os.getenv("BEEZA_COLLAB_BATCH_SIZE", "100"))))


def collaboration_event(db: Session, task: CollaborationTask, event_type: str,
                        actor: str, message: str, payload: dict[str, Any] | None = None,
                        severity: str = "INFO") -> None:
    body = bounded_payload(payload or {})
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{task.task_key}|{event_type}|{task.status}|{message}|{encoded}".encode()
    ).hexdigest()[:40]
    key = f"collab:{task.task_key}:{event_type}:{digest}"[:180]
    if db.scalar(select(RuntimeEvent.id).where(RuntimeEvent.event_key == key)):
        return
    now = utcnow()
    db.add(RuntimeEvent(
        event_key=key, mission_key=task.mission_key,
        dispatch_key=task.dispatch_key or task.task_key,
        runtime_key="beeza-collaboration", event_type=event_type,
        actor=actor[:120], message=message[:1000], severity=severity,
        payload=body if isinstance(body, dict) else {"value": body},
        occurred_at=now, created_at=now,
    ))


def create_message(db: Session, *, mission_key: str, task_key: str | None,
                   message_type: str, source_identity: str, target_identity: str,
                   subject: str, body: str, payload: dict[str, Any] | None = None,
                   status: str = "CREATED", reply_required: bool = False,
                   due_at: datetime | None = None) -> CollaborationMessage:
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"Unsupported message type: {message_type}")
    now = utcnow()
    row = CollaborationMessage(
        message_key=f"MSG-{uuid4().hex[:14].upper()}", mission_key=mission_key,
        task_key=task_key, message_type=message_type,
        source_identity=source_identity[:160], target_identity=target_identity[:160],
        subject=subject[:240], body=body[:3000],
        status=status if status in MESSAGE_STATUSES else "CREATED",
        payload=bounded_payload(payload or {}), reply_required=reply_required,
        due_at=aware(due_at), created_at=now,
        delivered_at=now if status in {"DELIVERED", "SEEN", "ACCEPTED", "IN_PROGRESS", "RESPONDED"} else None,
        acknowledged_at=now if status in {"ACCEPTED", "IN_PROGRESS", "RESPONDED"} else None,
        responded_at=now if status == "RESPONDED" else None,
    )
    db.add(row)
    return row


def get_task(db: Session, task_key: str) -> CollaborationTask | None:
    return db.scalar(select(CollaborationTask).where(CollaborationTask.task_key == task_key))


def dependencies_ready(db: Session, task: CollaborationTask) -> tuple[bool, list[str]]:
    keys = list(dict.fromkeys(task.depends_on or []))
    if not keys:
        return True, []
    rows = db.scalars(select(CollaborationTask).where(CollaborationTask.task_key.in_(keys))).all()
    status_by_key = {row.task_key: row.status for row in rows}
    waiting = [key for key in keys if status_by_key.get(key) != "COMPLETED"]
    return not waiting, waiting


def update_mission_waiting(db: Session, task: CollaborationTask, text: str) -> None:
    mission = db.scalar(select(Mission).where(Mission.mission_key == task.mission_key))
    if not mission:
        return
    mission.waiting_for = text[:180]
    if task.status in {"RUNNING", "DISPATCHING", "QUEUED"}:
        mission.status = "EXECUTING"
        mission.progress = max(mission.progress, 20)
    elif task.status == "WAITING_APPROVAL":
        mission.status = "WAITING_APPROVAL"
    elif task.status in {"BLOCKED", "FAILED", "ESCALATED"}:
        mission.status = "BLOCKED"


def work_prompt(task: CollaborationTask, mission: Mission) -> str:
    dependencies = ", ".join(task.depends_on or []) or "none"
    outputs = "\n".join(f"- {item}" for item in task.expected_outputs or []) or "- concise result"
    criteria = "\n".join(f"- {item}" for item in task.acceptance_criteria or []) or "- evidence-backed completion"
    return (
        f"BeezaOffice cross-runtime work package {task.task_key}\n"
        f"Mission: {mission.mission_key} — {mission.title}\n"
        f"Source: {task.source_identity}\nTarget: {task.target_identity}\n"
        f"Priority: {task.priority}\nDependencies: {dependencies}\n\n"
        f"Objective:\n{task.objective}\n\nExpected outputs:\n{outputs}\n\n"
        f"Acceptance criteria:\n{criteria}\n\n"
        "Return a structured summary, evidence, blockers, and a clear completion state. "
        "Do not execute consequential actions without the runtime approval policy."
    )


async def dispatch_task(db: Session, task: CollaborationTask) -> None:
    if task.status not in {"QUEUED", "REVISION"}:
        return
    ready, waiting = dependencies_ready(db, task)
    if not ready:
        task.status = "WAITING_DEPENDENCY"
        task.updated_at = utcnow()
        collaboration_event(db, task, "TASK_WAITING_DEPENDENCY", task.source_identity,
                            f"Waiting for dependencies: {', '.join(waiting)}.",
                            {"dependencies": waiting}, "WARNING")
        return

    runtime = db.scalar(select(RuntimeConnector).where(
        RuntimeConnector.runtime_key == task.target_runtime_key))
    mission = db.scalar(select(Mission).where(Mission.mission_key == task.mission_key))
    if not runtime or not mission:
        task.status = "BLOCKED"
        task.result = {"error": "Missing target runtime or mission"}
        task.updated_at = utcnow()
        collaboration_event(db, task, "TASK_BLOCKED", "Beeza Collaboration Bus",
                            "Task cannot dispatch because its mission or runtime is missing.",
                            task.result, "ERROR")
        return
    if not runtime.base_url:
        task.status = "BLOCKED"
        task.result = {"error": f"Runtime {runtime.display_name} is not configured"}
        task.updated_at = utcnow()
        collaboration_event(db, task, "TASK_BLOCKED", "Beeza Collaboration Bus",
                            f"{runtime.display_name} is not configured.", task.result, "ERROR")
        update_mission_waiting(db, task, f"{runtime.display_name} configuration required")
        return

    now = utcnow()
    dispatch = RuntimeDispatch(
        dispatch_key=f"DSP-{uuid4().hex[:12].upper()}", runtime_key=runtime.runtime_key,
        mission_key=mission.mission_key, status="DISPATCHING",
        output={"collaboration_task_key": task.task_key}, created_at=now, updated_at=now,
    )
    db.add(dispatch)
    db.flush()
    task.dispatch_key = dispatch.dispatch_key
    task.status = "DISPATCHING"
    task.attempts += 1
    task.last_progress_at = now
    task.next_follow_up_at = now + timedelta(seconds=FOLLOW_UP_SECONDS)
    task.updated_at = now
    collaboration_event(db, task, "HANDOFF_DISPATCHING", task.source_identity,
                        f"Sending {task.task_key} to {runtime.display_name}.",
                        {"runtime": runtime.runtime_key, "dispatch_key": dispatch.dispatch_key})
    db.commit()

    target_role = task.target_identity.removeprefix("agent:").lower()
    allowed_roles = {"office", "planner", "infra", "market", "research", "database", "engineer", "general"}
    preferred_roles = [target_role] if task.target_identity.startswith("agent:") and target_role in allowed_roles else []
    package = {
        "mission_key": mission.mission_key, "title": task.title,
        "objective": task.objective, "priority": task.priority,
        "prompt": work_prompt(task, mission), "roles": preferred_roles,
        "tags": ["beeza-collaboration", task.task_key, mission.priority.lower()],
        "instructions": "Typed BeezaOffice HANDOFF: acknowledge, preserve evidence, report blockers, and return required outputs.",
    }
    try:
        result = await dispatch_runtime(runtime_config(runtime), package)
        dispatch.remote_id = str(result.get("remote_id")) if result.get("remote_id") else None
        dispatch.status = normalize_remote_status(result.get("status") or "STARTED")
        dispatch.output = {
            "collaboration_task_key": task.task_key,
            "summary": str(result.get("output") or "")[:5000],
            "latency_ms": result.get("latency_ms"),
            "remote": bounded_payload(result.get("raw") or {}),
        }
        dispatch.updated_at = utcnow()
        runtime.status = "ONLINE"
        runtime.last_latency_ms = result.get("latency_ms")
        runtime.last_error = None
        runtime.last_probe_at = utcnow()
        task.status = {"COMPLETED": "COMPLETED" if task.review_policy == "AUTO" else "REVIEW",
                       "WAITING_APPROVAL": "WAITING_APPROVAL"}.get(dispatch.status, "RUNNING")
        task.last_progress_at = utcnow()
        task.updated_at = utcnow()
        if result.get("output") not in (None, ""):
            task.result = {"summary": str(result.get("output"))[:5000],
                           "runtime": runtime.runtime_key,
                           "dispatch_key": dispatch.dispatch_key,
                           "remote_id": dispatch.remote_id}
        create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                       message_type="ACCEPT", source_identity=task.target_identity,
                       target_identity=task.source_identity, subject=f"Accepted {task.task_key}",
                       body=f"{runtime.display_name} accepted the handoff; status {task.status}.",
                       payload={"dispatch_key": dispatch.dispatch_key, "remote_id": dispatch.remote_id},
                       status="ACCEPTED")
        collaboration_event(db, task, "TASK_ACCEPTED", task.target_identity,
                            f"{runtime.display_name} accepted {task.task_key}; status {task.status}.",
                            {"dispatch_key": dispatch.dispatch_key, "remote_id": dispatch.remote_id})
        update_mission_waiting(db, task, f"{task.target_identity} working on {task.task_key}")
    except RuntimeAdapterError as exc:
        dispatch.status = "FAILED"
        dispatch.error = str(exc)[:1200]
        dispatch.updated_at = utcnow()
        runtime.status = "OFFLINE"
        runtime.last_error = str(exc)[:800]
        runtime.last_probe_at = utcnow()
        task.status = "BLOCKED"
        task.result = {"error": str(exc)[:1200]}
        task.updated_at = utcnow()
        create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                       message_type="BLOCKED", source_identity=task.target_identity,
                       target_identity=task.source_identity, subject=f"Blocked {task.task_key}",
                       body=str(exc)[:3000], payload={"dispatch_key": dispatch.dispatch_key},
                       status="RESPONDED")
        collaboration_event(db, task, "TASK_BLOCKED", task.target_identity,
                            str(exc)[:1000], {"dispatch_key": dispatch.dispatch_key}, "ERROR")
        update_mission_waiting(db, task, f"{task.task_key} blocked on {runtime.display_name}")
    db.commit()


def mirror_dispatch_state(db: Session, task: CollaborationTask) -> None:
    if not task.dispatch_key:
        return
    dispatch = db.scalar(select(RuntimeDispatch).where(
        RuntimeDispatch.dispatch_key == task.dispatch_key))
    if not dispatch:
        return
    remote = normalize_remote_status(dispatch.status)
    previous = task.status
    if remote == "RUNNING" and task.status not in {"RUNNING", "REVISION"}:
        task.status = "RUNNING"
    elif remote == "WAITING_APPROVAL":
        task.status = "WAITING_APPROVAL"
    elif remote == "COMPLETED":
        task.status = "COMPLETED" if task.review_policy == "AUTO" else "REVIEW"
        task.result = {**(task.result or {}),
                       "summary": str((dispatch.output or {}).get("summary") or "")[:5000],
                       "runtime": dispatch.runtime_key, "dispatch_key": dispatch.dispatch_key,
                       "remote_id": dispatch.remote_id}
        task.next_follow_up_at = None
    elif remote in {"FAILED", "CANCELLED"}:
        task.status = "FAILED" if remote == "FAILED" else "CANCELLED"
        task.result = {**(task.result or {}), "error": dispatch.error,
                       "dispatch_status": remote}
        task.next_follow_up_at = None

    if task.status != previous:
        task.updated_at = utcnow()
        task.last_progress_at = utcnow()
        collaboration_event(db, task, f"TASK_{task.status}", task.target_identity,
                            f"{task.task_key} changed from {previous} to {task.status}.",
                            {"dispatch_key": dispatch.dispatch_key, "result": task.result},
                            "ERROR" if task.status in {"FAILED", "BLOCKED"} else "INFO")
        if task.status in {"COMPLETED", "REVIEW", "FAILED", "CANCELLED"}:
            create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                           message_type="COMPLETION" if task.status in {"COMPLETED", "REVIEW"} else "BLOCKED",
                           source_identity=task.target_identity, target_identity=task.source_identity,
                           subject=f"{task.task_key} {task.status.lower()}",
                           body=(task.result or {}).get("summary") or (task.result or {}).get("error") or task.status,
                           payload=task.result, status="RESPONDED")
        update_mission_waiting(db, task, f"{task.task_key}: {task.status}")


def follow_up_task(db: Session, task: CollaborationTask, now: datetime) -> None:
    if task.status not in {"DISPATCHING", "RUNNING", "WAITING_APPROVAL"}:
        return
    if task.deadline_at is not None and aware(task.deadline_at) <= now:
        task.status = "ESCALATED"
        task.next_follow_up_at = None
        task.updated_at = now
        create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                       message_type="ESCALATION", source_identity=task.source_identity,
                       target_identity="agent:Beeza Operator",
                       subject=f"Deadline missed · {task.task_key}",
                       body=f"{task.task_key} exceeded its deadline and requires operator attention.",
                       payload={"deadline_at": iso(task.deadline_at), "dispatch_key": task.dispatch_key},
                       status="ESCALATED", reply_required=True)
        collaboration_event(db, task, "TASK_DEADLINE_MISSED", "Beeza Follow-up Watchdog",
                            f"{task.task_key} exceeded its deadline.",
                            {"deadline_at": iso(task.deadline_at)}, "ERROR")
        update_mission_waiting(db, task, f"Deadline missed for {task.task_key}")
        return
    if task.next_follow_up_at is None or aware(task.next_follow_up_at) > now:
        return
    task.follow_up_count += 1
    task.updated_at = now
    task.next_follow_up_at = now + timedelta(seconds=FOLLOW_UP_SECONDS)
    if task.follow_up_count > MAX_FOLLOW_UPS:
        task.status = "ESCALATED"
        task.next_follow_up_at = None
        message_type, severity = "ESCALATION", "ERROR"
        body = f"{task.task_key} exceeded {MAX_FOLLOW_UPS} follow-ups and requires operator attention."
    else:
        message_type, severity = "FOLLOW_UP", "WARNING"
        body = f"Status update requested for {task.task_key}; follow-up {task.follow_up_count}/{MAX_FOLLOW_UPS}."
    create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                   message_type=message_type, source_identity=task.source_identity,
                   target_identity=task.target_identity,
                   subject=f"{message_type.replace('_', ' ').title()} · {task.task_key}",
                   body=body, payload={"follow_up_count": task.follow_up_count,
                                       "dispatch_key": task.dispatch_key},
                   status="ESCALATED" if message_type == "ESCALATION" else "DELIVERED",
                   reply_required=True, due_at=task.next_follow_up_at)
    collaboration_event(db, task, f"TASK_{message_type}", task.source_identity,
                        body, {"follow_up_count": task.follow_up_count}, severity)
    if task.status == "ESCALATED":
        update_mission_waiting(db, task, f"Operator attention required for {task.task_key}")


async def collaboration_tick() -> dict[str, int]:
    dispatched = updated = followed_up = 0
    now = utcnow()
    with SessionLocal() as db:
        tasks = db.scalars(
            select(CollaborationTask)
            .where(CollaborationTask.status.not_in(TERMINAL_TASK_STATUSES))
            .order_by(CollaborationTask.updated_at).limit(COLLAB_BATCH)
        ).all()
        for task in tasks:
            before = task.status
            mirror_dispatch_state(db, task)
            if task.status != before:
                updated += 1
            if task.status == "WAITING_DEPENDENCY":
                ready, _ = dependencies_ready(db, task)
                if ready:
                    task.status = "QUEUED"
                    task.updated_at = now
            if task.status in {"QUEUED", "REVISION"} and task.auto_dispatch:
                await dispatch_task(db, task)
                dispatched += 1
            previous = task.follow_up_count
            follow_up_task(db, task, now)
            if task.follow_up_count != previous:
                followed_up += 1
        db.commit()
    return {"dispatched": dispatched, "updated": updated, "followed_up": followed_up}


async def collaboration_worker() -> None:
    while True:
        try:
            result = await collaboration_tick()
            redis_client.hset("beezaoffice:collaboration-worker", mapping={
                "status": "online", "last_tick_at": utcnow().isoformat(),
                "last_dispatched": str(result["dispatched"]),
                "last_updated": str(result["updated"]),
                "last_followed_up": str(result["followed_up"]),
                "interval_seconds": str(COLLAB_INTERVAL),
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset("beezaoffice:collaboration-worker", mapping={
                "status": "degraded", "last_tick_at": utcnow().isoformat(),
                "last_error": str(exc)[:500],
            })
        await asyncio.sleep(COLLAB_INTERVAL)
