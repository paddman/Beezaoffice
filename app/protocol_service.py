from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask
from collaboration_service import collaboration_event, create_message
from main import Mission, MissionEvent, SessionLocal, bounded_payload, redis_client, utcnow
from phase8_app import routed_dispatch_task
from protocol_models import ProtocolEvent, ProtocolTask, TERMINAL_PROTOCOL_STATES

PROTOCOL_ENABLED = os.getenv("BEEZA_PROTOCOL_ENABLED", "true").lower() not in {
    "0", "false", "no", "off",
}
PROTOCOL_INTERVAL = max(1.0, float(os.getenv("BEEZA_PROTOCOL_INTERVAL_SECONDS", "2")))
PROTOCOL_BATCH = max(1, min(500, int(os.getenv("BEEZA_PROTOCOL_BATCH_SIZE", "100"))))
PROTOCOL_SYNC_TIMEOUT = max(1.0, min(120.0, float(os.getenv("BEEZA_PROTOCOL_SYNC_TIMEOUT_SECONDS", "20"))))
PROTOCOL_PUBLIC_URL = os.getenv("BEEZA_PUBLIC_URL", "http://localhost:8080").rstrip("/")

COLLAB_TO_A2A_STATE = {
    "DRAFT": "TASK_STATE_SUBMITTED",
    "WAITING_DEPENDENCY": "TASK_STATE_WORKING",
    "QUEUED": "TASK_STATE_WORKING",
    "DISPATCHING": "TASK_STATE_WORKING",
    "RUNNING": "TASK_STATE_WORKING",
    "REVISION": "TASK_STATE_WORKING",
    "WAITING_APPROVAL": "TASK_STATE_INPUT_REQUIRED",
    "REVIEW": "TASK_STATE_INPUT_REQUIRED",
    "COMPLETED": "TASK_STATE_COMPLETED",
    "FAILED": "TASK_STATE_FAILED",
    "BLOCKED": "TASK_STATE_FAILED",
    "ESCALATED": "TASK_STATE_FAILED",
    "CANCELLED": "TASK_STATE_CANCELED",
}


def compact_text(value: Any, limit: int = 12000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def message_text(parts: list[Any]) -> str:
    output: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        data = getattr(part, "data", None)
        if text:
            output.append(str(text))
        elif data:
            output.append(json.dumps(data, ensure_ascii=False, default=str))
    return "\n\n".join(output).strip()


def openai_messages_text(messages: list[Any]) -> str:
    rows: list[str] = []
    for message in messages:
        content = message.content
        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        pieces.append(str(text))
            content = "\n".join(pieces)
        rows.append(f"{message.role.upper()}: {content}")
    return "\n\n".join(rows)[:20000]


def next_sequence(db: Session, task_id: str) -> int:
    current = db.scalar(
        select(func.coalesce(func.max(ProtocolEvent.sequence), 0)).where(
            ProtocolEvent.task_id == task_id
        )
    )
    return int(current or 0) + 1


def add_protocol_event(
    db: Session,
    row: ProtocolTask,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> ProtocolEvent:
    event = ProtocolEvent(
        event_key=f"PGEVT-{uuid4().hex[:18].upper()}",
        task_id=row.task_id,
        sequence=next_sequence(db, row.task_id),
        event_type=event_type,
        payload=bounded_payload(payload or {}, max_chars=12000),
        occurred_at=utcnow(),
    )
    db.add(event)
    return event


def status_message_for(task: CollaborationTask, state: str) -> str:
    if state == "TASK_STATE_COMPLETED":
        return f"{task.task_key} completed and is available as an artifact."
    if state == "TASK_STATE_INPUT_REQUIRED":
        return f"{task.task_key} requires human input or approval."
    if state == "TASK_STATE_FAILED":
        return str((task.result or {}).get("error") or f"{task.task_key} failed")[:2000]
    if state == "TASK_STATE_CANCELED":
        return f"{task.task_key} was canceled."
    return f"{task.task_key} is {task.status.lower().replace('_', ' ')}."


def artifacts_for(task: CollaborationTask) -> list[dict[str, Any]]:
    if task.status not in {"COMPLETED", "REVIEW", "WAITING_APPROVAL", "FAILED", "BLOCKED"}:
        return []
    result = bounded_payload(task.result or {}, max_chars=20000)
    summary = compact_text((task.result or {}).get("summary") or (task.result or {}).get("error") or result, 12000)
    artifact = {
        "artifactId": f"artifact-{task.task_key.lower()}",
        "name": task.title,
        "description": "BeezaOffice governed task result and evidence envelope.",
        "parts": [
            {"text": summary},
            {"data": result if isinstance(result, dict) else {"value": result}},
        ],
        "metadata": {
            "missionKey": task.mission_key,
            "collaborationTaskKey": task.task_key,
            "runtimeKey": task.target_runtime_key,
            "dispatchKey": task.dispatch_key,
            "verification": (task.result or {}).get("verification"),
        },
    }
    return [artifact]


def sync_protocol_task(db: Session, row: ProtocolTask) -> ProtocolTask:
    if not row.collaboration_task_key:
        return row
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == row.collaboration_task_key
        )
    )
    if task is None:
        if row.state not in TERMINAL_PROTOCOL_STATES:
            row.state = "TASK_STATE_FAILED"
            row.status_message = "Linked BeezaOffice task no longer exists."
            row.error = row.status_message
            row.completed_at = utcnow()
            row.updated_at = utcnow()
            add_protocol_event(db, row, "TASK_STATUS_UPDATE", {"state": row.state, "message": row.status_message})
        return row

    next_state = COLLAB_TO_A2A_STATE.get(task.status, "TASK_STATE_WORKING")
    next_message = status_message_for(task, next_state)
    next_artifacts = artifacts_for(task)
    changed = (
        row.state != next_state
        or row.status_message != next_message
        or row.artifacts != next_artifacts
    )
    row.state = next_state
    row.status_message = next_message
    row.artifacts = next_artifacts
    row.error = next_message if next_state == "TASK_STATE_FAILED" else None
    row.updated_at = utcnow()
    if next_state in TERMINAL_PROTOCOL_STATES and row.completed_at is None:
        row.completed_at = utcnow()
    if changed:
        add_protocol_event(
            db,
            row,
            "TASK_STATUS_UPDATE",
            {
                "state": next_state,
                "message": next_message,
                "artifactCount": len(next_artifacts),
                "collaborationTaskStatus": task.status,
            },
        )
        if next_artifacts:
            add_protocol_event(
                db,
                row,
                "TASK_ARTIFACT_UPDATE",
                {"artifacts": next_artifacts},
            )
    return row


def a2a_task_view(row: ProtocolTask) -> dict[str, Any]:
    status: dict[str, Any] = {
        "state": row.state,
        "timestamp": row.updated_at.isoformat(),
        "message": {
            "messageId": f"status-{row.task_id}",
            "role": "ROLE_AGENT",
            "parts": [{"text": row.status_message}],
        },
    }
    return {
        "id": row.task_id,
        "contextId": row.context_id,
        "status": status,
        "artifacts": row.artifacts or [],
        "history": [
            {
                "messageId": row.message_id,
                "role": "ROLE_USER",
                "parts": [{"text": compact_text((row.request_payload or {}).get("text"), 20000)}],
            }
        ],
        "metadata": {
            "protocol": row.protocol,
            "missionKey": row.mission_key,
            "collaborationTaskKey": row.collaboration_task_key,
            "sopRunKey": row.sop_run_key,
        },
    }


def get_protocol_task(db: Session, task_id: str) -> ProtocolTask | None:
    return db.scalar(select(ProtocolTask).where(ProtocolTask.task_id == task_id))


def existing_message_task(
    db: Session,
    *,
    protocol: str,
    client_identity: str,
    message_id: str,
) -> ProtocolTask | None:
    return db.scalar(
        select(ProtocolTask).where(
            ProtocolTask.protocol == protocol,
            ProtocolTask.client_identity == client_identity,
            ProtocolTask.message_id == message_id,
        )
    )


async def create_protocol_task(
    db: Session,
    *,
    protocol: str,
    client_identity: str,
    message_id: str,
    context_id: str,
    text: str,
    title: str | None = None,
    priority: str = "NORMAL",
    required_skills: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    required_tools: list[str] | None = None,
    required_clearance: str = "INTERNAL",
    preferred_runtime_key: str | None = None,
    fixed_runtime: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ProtocolTask:
    duplicate = existing_message_task(
        db,
        protocol=protocol,
        client_identity=client_identity,
        message_id=message_id,
    )
    if duplicate is not None:
        sync_protocol_task(db, duplicate)
        db.commit()
        return duplicate

    objective = text.strip()
    if len(objective) < 10:
        objective = f"Process the following protocol request and return a verified result: {objective}"
    objective = objective[:3000]
    now = utcnow()
    short = uuid4().hex[:10].upper()
    mission_key = f"GW-{short}"
    task_key = f"TASK-{uuid4().hex[:12].upper()}"
    gateway_task_id = f"task-{uuid4()}"
    display_title = (title or objective.splitlines()[0] or "Protocol request")[:200]
    mission = Mission(
        mission_key=mission_key,
        title=display_title,
        commander="Beeza Protocol Gateway",
        status="EXECUTING",
        priority=priority,
        progress=5,
        waiting_for="Protocol gateway routing",
        objective=objective[:600],
        created_at=now,
    )
    automatic = not fixed_runtime
    routing_context = {
        "routing_mode": "AUTO" if automatic else "FIXED",
        "required_skills": sorted(set(required_skills or [])),
        "required_capabilities": sorted(set(required_capabilities or [])),
        "required_tools": sorted(set(required_tools or [])),
        "required_clearance": required_clearance,
        "preferred_runtime_key": preferred_runtime_key,
        "strict_skills": False,
        "allow_overflow": False,
        "routing": {
            "mode": "AUTO" if automatic else "FIXED",
            "status": "QUEUED",
            "attempts": 0,
        },
        "protocol_gateway": {
            "protocol": protocol,
            "task_id": gateway_task_id,
            "message_id": message_id,
            "context_id": context_id,
            "client_identity": client_identity,
        },
        **(metadata or {}),
    }
    target_identity = "agent:auto" if automatic else f"runtime:{preferred_runtime_key}"
    target_runtime = "auto" if automatic else str(preferred_runtime_key)
    task = CollaborationTask(
        task_key=task_key,
        mission_key=mission_key,
        parent_task_key=None,
        title=display_title,
        objective=objective,
        source_identity="service:protocol",
        target_identity=target_identity,
        target_runtime_key=target_runtime,
        status="QUEUED",
        priority=priority,
        review_policy="AUTO",
        auto_dispatch=True,
        depends_on=[],
        inputs=[{"type": "protocol_message", "protocol": protocol, "text": objective}],
        expected_outputs=["structured response", "supporting evidence", "clear completion state"],
        acceptance_criteria=["Response addresses the request", "Evidence or provenance is preserved"],
        context=bounded_payload(routing_context, max_chars=15000),
        result={},
        dispatch_key=None,
        attempts=0,
        follow_up_count=0,
        last_progress_at=now,
        next_follow_up_at=None,
        deadline_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    row = ProtocolTask(
        task_id=gateway_task_id,
        protocol=protocol,
        client_identity=client_identity,
        message_id=message_id,
        context_id=context_id,
        state="TASK_STATE_SUBMITTED",
        mission_key=mission_key,
        collaboration_task_key=task_key,
        sop_run_key=None,
        request_payload=bounded_payload(
            {"text": objective, "title": display_title, "metadata": metadata or {}},
            max_chars=20000,
        ),
        artifacts=[],
        status_message="Request accepted by BeezaOffice.",
        error=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    db.add_all([mission, task, row])
    db.flush()
    create_message(
        db,
        mission_key=mission_key,
        task_key=task_key,
        message_type="HANDOFF",
        source_identity="service:protocol",
        target_identity="service:scheduler" if automatic else target_identity,
        subject=f"Protocol request · {display_title}",
        body=objective,
        payload={
            "protocol": protocol,
            "gateway_task_id": gateway_task_id,
            "client_identity": client_identity,
            "preferred_runtime_key": preferred_runtime_key,
        },
        status="DELIVERED",
        reply_required=True,
        due_at=task.deadline_at,
    )
    collaboration_event(
        db,
        task,
        "PROTOCOL_TASK_CREATED",
        "service:protocol",
        f"Created {task_key} from {protocol} request {message_id}.",
        {"protocol_task_id": gateway_task_id, "context_id": context_id},
    )
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor="service:protocol",
            event_type="PROTOCOL_REQUEST_ACCEPTED",
            message=f"Accepted {protocol} request as {gateway_task_id}."[:800],
            created_at=now,
        )
    )
    add_protocol_event(
        db,
        row,
        "TASK_SUBMITTED",
        {"state": row.state, "missionKey": mission_key, "collaborationTaskKey": task_key},
    )
    db.commit()
    db.refresh(task)
    await routed_dispatch_task(db, task)
    sync_protocol_task(db, row)
    db.commit()
    db.refresh(row)
    return row


async def wait_for_protocol_task(
    task_id: str,
    timeout_seconds: float | None = None,
) -> ProtocolTask | None:
    timeout = PROTOCOL_SYNC_TIMEOUT if timeout_seconds is None else max(0.0, timeout_seconds)
    deadline = asyncio.get_running_loop().time() + timeout
    latest: ProtocolTask | None = None
    while True:
        with SessionLocal() as db:
            latest = get_protocol_task(db, task_id)
            if latest is None:
                return None
            sync_protocol_task(db, latest)
            db.commit()
            db.refresh(latest)
            if latest.state in TERMINAL_PROTOCOL_STATES or latest.state == "TASK_STATE_INPUT_REQUIRED":
                return latest
        if asyncio.get_running_loop().time() >= deadline:
            return latest
        await asyncio.sleep(0.5)


def protocol_stats(db: Session) -> dict[str, Any]:
    rows = list(db.scalars(select(ProtocolTask)).all())
    states: dict[str, int] = {}
    protocols: dict[str, int] = {}
    for row in rows:
        states[row.state] = states.get(row.state, 0) + 1
        protocols[row.protocol] = protocols.get(row.protocol, 0) + 1
    return {
        "tasks": len(rows),
        "active_tasks": sum(row.state not in TERMINAL_PROTOCOL_STATES for row in rows),
        "completed_tasks": states.get("TASK_STATE_COMPLETED", 0),
        "failed_tasks": states.get("TASK_STATE_FAILED", 0),
        "states": dict(sorted(states.items())),
        "protocols": dict(sorted(protocols.items())),
        "events": db.query(ProtocolEvent).count(),
    }


def rotating_protocol_tasks(db: Session, limit: int) -> list[ProtocolTask]:
    cursor = int(redis_client.get("beezaoffice:protocol-task-cursor") or 0)
    statement = (
        select(ProtocolTask)
        .where(
            ProtocolTask.state.not_in(TERMINAL_PROTOCOL_STATES),
            ProtocolTask.id > cursor,
        )
        .order_by(ProtocolTask.id.asc())
        .limit(limit)
    )
    rows = list(db.scalars(statement).all())
    if not rows and cursor:
        rows = list(
            db.scalars(
                select(ProtocolTask)
                .where(ProtocolTask.state.not_in(TERMINAL_PROTOCOL_STATES))
                .order_by(ProtocolTask.id.asc())
                .limit(limit)
            ).all()
        )
    redis_client.set("beezaoffice:protocol-task-cursor", str(rows[-1].id if rows else 0))
    return rows


def protocol_tick() -> dict[str, int]:
    processed = changed = completed = failed = 0
    with SessionLocal() as db:
        rows = rotating_protocol_tasks(db, max(PROTOCOL_BATCH * 5, 200))[:PROTOCOL_BATCH]
        for row in rows:
            previous = row.state
            sync_protocol_task(db, row)
            processed += 1
            changed += row.state != previous
            completed += row.state == "TASK_STATE_COMPLETED" and previous != row.state
            failed += row.state == "TASK_STATE_FAILED" and previous != row.state
        db.commit()
    return {"processed": processed, "changed": changed, "completed": completed, "failed": failed}


async def protocol_worker() -> None:
    while True:
        try:
            result = await asyncio.to_thread(protocol_tick)
            redis_client.hset(
                "beezaoffice:protocol-worker",
                mapping={
                    "status": "running",
                    "last_tick_at": utcnow().isoformat(),
                    "last_processed": str(result["processed"]),
                    "last_changed": str(result["changed"]),
                    "last_completed": str(result["completed"]),
                    "last_failed": str(result["failed"]),
                    "interval_seconds": str(PROTOCOL_INTERVAL),
                    "last_error": "",
                },
            )
        except Exception as exc:
            redis_client.hset(
                "beezaoffice:protocol-worker",
                mapping={
                    "status": "error",
                    "last_tick_at": utcnow().isoformat(),
                    "last_error": str(exc)[:1000],
                },
            )
        await asyncio.sleep(PROTOCOL_INTERVAL)


def webhook_digest(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()
