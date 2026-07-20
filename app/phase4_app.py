from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import (
    CollaborationMessage, CollaborationMessageCreate, CollaborationTask,
    HandoffCreate, MESSAGE_STATUSES, TASK_STATUSES, TaskAction, TaskReview,
    aware, message_view, task_view,
)
from collaboration_service import (
    COLLAB_INTERVAL, FOLLOW_UP_SECONDS, MAX_FOLLOW_UPS,
    collaboration_event, collaboration_tick, collaboration_worker, create_message,
    dispatch_task, get_task,
)
from main import (
    Mission, MissionEvent, RuntimeConnector, app, bounded_payload, db_session,
    redis_client, require_token, utcnow,
)
import phase3_app  # noqa: F401 — install Phase 3 models, routes, and worker

app.version = "0.5.0"
_worker_task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def start_collaboration_worker() -> None:
    global _worker_task
    if os.getenv("BEEZA_COLLAB_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        redis_client.hset("beezaoffice:collaboration-worker", mapping={"status": "disabled"})
        return
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(collaboration_worker(), name="beeza-collaboration-worker")


@app.on_event("shutdown")
async def stop_collaboration_worker() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _worker_task
    _worker_task = None


@app.get("/api/collaboration/worker")
def worker_status() -> dict[str, Any]:
    state = redis_client.hgetall("beezaoffice:collaboration-worker")
    return {
        "status": state.get("status", "starting"),
        "last_tick_at": state.get("last_tick_at"),
        "last_dispatched": int(state.get("last_dispatched", "0") or 0),
        "last_updated": int(state.get("last_updated", "0") or 0),
        "last_followed_up": int(state.get("last_followed_up", "0") or 0),
        "interval_seconds": float(state.get("interval_seconds", str(COLLAB_INTERVAL))),
        "follow_up_seconds": FOLLOW_UP_SECONDS,
        "max_follow_ups": MAX_FOLLOW_UPS,
    }


@app.post("/api/collaboration/tick", dependencies=[Depends(require_token)])
async def run_tick() -> dict[str, Any]:
    return {"ok": True, **(await collaboration_tick())}


@app.get("/api/missions/{mission_key}/collaboration")
def mission_collaboration(mission_key: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    if db.scalar(select(Mission.id).where(Mission.mission_key == mission_key)) is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    tasks = db.scalars(select(CollaborationTask).where(
        CollaborationTask.mission_key == mission_key).order_by(CollaborationTask.created_at)).all()
    messages = db.scalars(select(CollaborationMessage).where(
        CollaborationMessage.mission_key == mission_key)
        .order_by(CollaborationMessage.created_at.desc()).limit(300)).all()
    return {
        "mission_key": mission_key,
        "tasks": [task_view(row) for row in tasks],
        "messages": [message_view(row) for row in messages],
        "stats": {
            "total": len(tasks),
            "running": sum(row.status in {"DISPATCHING", "RUNNING"} for row in tasks),
            "waiting": sum(row.status in {"WAITING_DEPENDENCY", "WAITING_APPROVAL", "REVIEW"} for row in tasks),
            "blocked": sum(row.status in {"BLOCKED", "FAILED", "ESCALATED"} for row in tasks),
            "completed": sum(row.status == "COMPLETED" for row in tasks),
        },
    }


@app.post("/api/missions/{mission_key}/handoffs",
          dependencies=[Depends(require_token)], status_code=201)
async def create_handoff(mission_key: str, payload: HandoffCreate,
                         db: Session = Depends(db_session)) -> dict[str, Any]:
    mission = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    runtime = db.scalar(select(RuntimeConnector).where(
        RuntimeConnector.runtime_key == payload.target_runtime_key))
    if not runtime:
        raise HTTPException(status_code=404, detail="Target runtime not found")
    dependencies = list(dict.fromkeys(payload.depends_on))
    if dependencies:
        known = set(db.scalars(select(CollaborationTask.task_key).where(
            CollaborationTask.task_key.in_(dependencies),
            CollaborationTask.mission_key == mission_key)).all())
        unknown = [key for key in dependencies if key not in known]
        if unknown:
            raise HTTPException(status_code=409, detail=f"Unknown dependencies: {', '.join(unknown)}")

    now = utcnow()
    task = CollaborationTask(
        task_key=f"TASK-{uuid4().hex[:12].upper()}", mission_key=mission_key,
        parent_task_key=payload.parent_task_key, title=payload.title,
        objective=payload.objective, source_identity=payload.source_identity,
        target_identity=payload.target_identity or f"runtime:{runtime.runtime_key}",
        target_runtime_key=runtime.runtime_key,
        status="WAITING_DEPENDENCY" if dependencies else "QUEUED",
        priority=payload.priority, review_policy=payload.review_policy,
        auto_dispatch=payload.auto_dispatch, depends_on=dependencies,
        inputs=bounded_payload(payload.inputs), expected_outputs=payload.expected_outputs,
        acceptance_criteria=payload.acceptance_criteria,
        context=bounded_payload(payload.context), result={}, attempts=0,
        follow_up_count=0, last_progress_at=now, next_follow_up_at=None,
        deadline_at=aware(payload.deadline_at), created_at=now, updated_at=now,
    )
    db.add(task)
    db.flush()
    create_message(db, mission_key=mission_key, task_key=task.task_key,
                   message_type="HANDOFF", source_identity=task.source_identity,
                   target_identity=task.target_identity, subject=task.title,
                   body=task.objective, payload={
                       "priority": task.priority, "depends_on": task.depends_on,
                       "expected_outputs": task.expected_outputs,
                       "acceptance_criteria": task.acceptance_criteria,
                   }, status="DELIVERED", reply_required=True, due_at=task.deadline_at)
    collaboration_event(db, task, "HANDOFF_CREATED", task.source_identity,
                        f"Created handoff {task.task_key} for {task.target_identity}.",
                        {"depends_on": task.depends_on, "runtime": task.target_runtime_key})
    db.add(MissionEvent(mission_key=mission_key, actor=task.source_identity[:80],
                        event_type="HANDOFF_CREATED",
                        message=f"{task.task_key} → {task.target_identity}: {task.title}"[:800],
                        created_at=now))
    mission.status = "EXECUTING"
    mission.waiting_for = f"Collaboration task {task.task_key} queued"
    db.commit()
    db.refresh(task)
    if task.auto_dispatch and task.status == "QUEUED":
        await dispatch_task(db, task)
        db.refresh(task)
    return task_view(task)


@app.get("/api/collaboration/tasks")
def list_tasks(mission_key: str | None = None, status: str | None = Query(default=None),
               limit: int = Query(default=200, ge=1, le=1000),
               db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    statement = select(CollaborationTask)
    if mission_key:
        statement = statement.where(CollaborationTask.mission_key == mission_key)
    if status:
        normalized = status.upper()
        if normalized not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown task status")
        statement = statement.where(CollaborationTask.status == normalized)
    rows = db.scalars(statement.order_by(CollaborationTask.created_at.desc()).limit(limit)).all()
    return [task_view(row) for row in rows]


@app.post("/api/collaboration/tasks/{task_key}/actions",
          dependencies=[Depends(require_token)])
async def task_action(task_key: str, payload: TaskAction,
                      db: Session = Depends(db_session)) -> dict[str, Any]:
    task = get_task(db, task_key)
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    now = utcnow()
    action, note = payload.action, payload.note or ""
    if action == "accept":
        task.status, task.auto_dispatch = "QUEUED", True
        task.next_follow_up_at = now + timedelta(seconds=FOLLOW_UP_SECONDS)
        message_type = "ACCEPT"
    elif action == "block":
        task.status = "BLOCKED"
        task.result = {**(task.result or {}), **payload.result, "blocker": note}
        task.next_follow_up_at = None
        message_type = "BLOCKED"
    elif action == "resume":
        task.status, task.next_follow_up_at = "QUEUED", None
        message_type = "RESPONSE"
    elif action == "complete":
        task.status = "COMPLETED"
        task.result = {**(task.result or {}), **payload.result, "note": note}
        task.next_follow_up_at = None
        message_type = "COMPLETION"
    elif action == "cancel":
        task.status, task.next_follow_up_at = "CANCELLED", None
        message_type = "DECISION"
    else:
        task.status, task.dispatch_key = "QUEUED", None
        task.follow_up_count, task.next_follow_up_at = 0, None
        message_type = "REVISION"
    task.updated_at = task.last_progress_at = now
    create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                   message_type=message_type, source_identity="agent:Beeza Operator",
                   target_identity=task.target_identity, subject=f"{action.title()} {task.task_key}",
                   body=note or f"Task action: {action}", payload=payload.result,
                   status="DELIVERED")
    collaboration_event(db, task, f"TASK_{task.status}", "Beeza Operator",
                        note or f"Task action {action} applied.", payload.result,
                        "ERROR" if task.status == "BLOCKED" else "INFO")
    db.commit()
    db.refresh(task)
    if task.status == "QUEUED" and task.auto_dispatch:
        await dispatch_task(db, task)
        db.refresh(task)
    return task_view(task)


@app.post("/api/collaboration/tasks/{task_key}/review",
          dependencies=[Depends(require_token)])
async def review_task(task_key: str, payload: TaskReview,
                      db: Session = Depends(db_session)) -> dict[str, Any]:
    task = get_task(db, task_key)
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    if task.status not in {"REVIEW", "COMPLETED"}:
        raise HTTPException(status_code=409, detail="Task is not awaiting review")
    now = utcnow()
    if payload.decision == "accept":
        task.status, message_type = "COMPLETED", "DECISION"
    elif payload.decision == "revise":
        task.status, task.dispatch_key = "REVISION", None
        task.follow_up_count, task.next_follow_up_at = 0, None
        message_type = "REVISION"
    else:
        task.status, task.next_follow_up_at = "FAILED", None
        message_type = "REJECT"
    task.updated_at = task.last_progress_at = now
    create_message(db, mission_key=task.mission_key, task_key=task.task_key,
                   message_type=message_type, source_identity=task.source_identity,
                   target_identity=task.target_identity,
                   subject=f"Review {payload.decision} · {task.task_key}",
                   body=payload.note or payload.decision,
                   payload={"decision": payload.decision}, status="DELIVERED")
    collaboration_event(db, task, f"REVIEW_{payload.decision.upper()}",
                        task.source_identity,
                        payload.note or f"Review decision: {payload.decision}.",
                        {"decision": payload.decision},
                        "ERROR" if payload.decision == "reject" else "INFO")
    db.commit()
    db.refresh(task)
    if task.status == "REVISION" and task.auto_dispatch:
        await dispatch_task(db, task)
        db.refresh(task)
    return task_view(task)


@app.get("/api/collaboration/inbox")
def inbox(recipient: str | None = None, mission_key: str | None = None,
          status: str | None = None,
          limit: int = Query(default=200, ge=1, le=1000),
          db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    statement = select(CollaborationMessage)
    if recipient:
        statement = statement.where(CollaborationMessage.target_identity == recipient)
    if mission_key:
        statement = statement.where(CollaborationMessage.mission_key == mission_key)
    if status:
        normalized = status.upper()
        if normalized not in MESSAGE_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown message status")
        statement = statement.where(CollaborationMessage.status == normalized)
    rows = db.scalars(statement.order_by(CollaborationMessage.created_at.desc()).limit(limit)).all()
    return [message_view(row) for row in rows]


@app.post("/api/missions/{mission_key}/messages",
          dependencies=[Depends(require_token)], status_code=201)
def post_message(mission_key: str, payload: CollaborationMessageCreate,
                 db: Session = Depends(db_session)) -> dict[str, Any]:
    if db.scalar(select(Mission.id).where(Mission.mission_key == mission_key)) is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    if payload.task_key:
        task = get_task(db, payload.task_key)
        if task is None:
            raise HTTPException(status_code=404, detail="Collaboration task not found")
        if task.mission_key != mission_key:
            raise HTTPException(status_code=409, detail="Task belongs to another mission")
    row = create_message(db, mission_key=mission_key, task_key=payload.task_key,
                         message_type=payload.message_type,
                         source_identity=payload.source_identity,
                         target_identity=payload.target_identity,
                         subject=payload.subject, body=payload.body,
                         payload=payload.payload, status="DELIVERED",
                         reply_required=payload.reply_required, due_at=payload.due_at)
    db.commit()
    db.refresh(row)
    return message_view(row)
