from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import JSON, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from main import (
    Base,
    Mission,
    RuntimeConnector,
    RuntimeDispatch,
    SessionLocal,
    app,
    bounded_payload,
    db_session,
    redis_client,
    require_token,
    runtime_config,
    utcnow,
)
from phase2_app import (
    add_mission_event,
    get_dispatch_bundle,
    normalize_remote_status,
    phase2_dispatch_view,
    remove_route,
    update_mission_from_dispatch,
)
from runtime_adapters import RuntimeAdapterError, get_runtime_status

app.version = "0.4.0"


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    dispatch_key: Mapped[str] = mapped_column(String(100), index=True)
    runtime_key: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="Runtime")
    message: Mapped[str] = mapped_column(String(1000))
    severity: Mapped[str] = mapped_column(String(20), default="INFO")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_type(value: Any, fallback: str = "RUNTIME_UPDATE") -> str:
    text = str(value or fallback).strip().upper()
    text = text.replace("-", "_").replace(".", "_").replace(" ", "_")
    return "".join(char for char in text if char.isalnum() or char == "_")[:100] or fallback


def severity_for(value: Any, event_type: str) -> str:
    explicit = str(value or "").upper()
    if explicit in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return explicit
    if any(word in event_type for word in ("FAILED", "ERROR", "DENIED")):
        return "ERROR"
    if any(word in event_type for word in ("WAITING", "APPROVAL", "BLOCKED")):
        return "WARNING"
    return "INFO"


def event_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return utcnow()
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utcnow()


def event_message(item: Any, fallback: str) -> str:
    if isinstance(item, str):
        return item[:1000]
    if isinstance(item, dict):
        value = first(item, "message", "summary", "content", "text", "description", "title", "event")
        if value not in (None, ""):
            return str(value)[:1000]
        return json.dumps(item, ensure_ascii=False, default=str)[:1000]
    return str(item or fallback)[:1000]


def event_key(dispatch_key: str, source: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{dispatch_key}|{source}|{encoded}".encode()).hexdigest()[:40]
    return f"{dispatch_key}:{source}:{digest}"[:180]


def event_view(row: RuntimeEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "key": row.event_key,
        "mission_key": row.mission_key,
        "dispatch_key": row.dispatch_key,
        "runtime_key": row.runtime_key,
        "type": row.event_type,
        "actor": row.actor,
        "message": row.message,
        "severity": row.severity,
        "payload": row.payload,
        "occurred_at": row.occurred_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def add_event(
    db: Session,
    dispatch: RuntimeDispatch,
    runtime: RuntimeConnector,
    *,
    source: str,
    event_type: Any,
    actor: Any,
    message: str,
    payload: Any,
    occurred_at: Any = None,
    severity: Any = None,
    seen: set[str],
) -> int:
    key = event_key(dispatch.dispatch_key, source, payload)
    if key in seen or db.scalar(select(RuntimeEvent.id).where(RuntimeEvent.event_key == key)):
        return 0
    seen.add(key)
    normalized = normalize_type(event_type)
    safe_payload = bounded_payload(payload, max_chars=9000)
    if not isinstance(safe_payload, dict):
        safe_payload = {"value": safe_payload}
    db.add(
        RuntimeEvent(
            event_key=key,
            mission_key=dispatch.mission_key,
            dispatch_key=dispatch.dispatch_key,
            runtime_key=runtime.runtime_key,
            event_type=normalized,
            actor=str(actor or runtime.display_name)[:120],
            message=message[:1000],
            severity=severity_for(severity, normalized),
            payload=safe_payload,
            occurred_at=event_time(occurred_at),
            created_at=utcnow(),
        )
    )
    return 1


def ingest_snapshot(
    db: Session,
    dispatch: RuntimeDispatch,
    runtime: RuntimeConnector,
    raw: Any,
) -> int:
    if not isinstance(raw, dict):
        return 0
    seen: set[str] = set()
    added = 0
    platform = runtime.platform.lower()

    if platform == "cherryagent":
        run = raw.get("run") if isinstance(raw.get("run"), dict) else raw
        status = first(run, "status", "state")
        updated = first(run, "updatedAt", "updated_at", "completedAt", "startedAt", "createdAt")
        if status:
            added += add_event(
                db, dispatch, runtime,
                source="run-status",
                event_type=f"RUN_{status}",
                actor="CherryAgent Orchestrator",
                message=f"Remote run is {status}.",
                payload={"status": status},
                occurred_at=updated,
                seen=seen,
            )

        tasks = run.get("tasks") if isinstance(run, dict) else []
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            task_id = first(task, "id", "taskId", "key") or "task"
            task_status = first(task, "status", "state") or "updated"
            title = first(task, "title", "objective", "name", "description") or task_id
            actor = first(task, "role", "agentRole", "assignee", "agent") or "CherryAgent"
            occurred = first(task, "updatedAt", "updated_at", "completedAt", "startedAt", "createdAt")
            added += add_event(
                db, dispatch, runtime,
                source=f"task:{task_id}:{task_status}:{occurred or ''}",
                event_type=f"TASK_{task_status}",
                actor=actor,
                message=f"{title} · {task_status}",
                payload=task,
                occurred_at=occurred,
                severity=first(task, "level", "severity"),
                seen=seen,
            )

        for collection, fallback_type, fallback_actor in (
            ("handoffs", "HANDOFF", "CherryAgent Handoff"),
            ("evidence", "EVIDENCE_CAPTURED", "CherryAgent Evidence"),
            ("logs", "RUNTIME_LOG", "CherryAgent"),
        ):
            items = raw.get(collection)
            for index, item in enumerate(items if isinstance(items, list) else []):
                if not isinstance(item, dict):
                    item = {"value": item}
                item_id = first(item, "id", "logId", "handoffId", "evidenceId") or index
                occurred = first(item, "createdAt", "created_at", "updatedAt", "at", "timestamp")
                kind = first(item, "type", "eventType", "event_type") or fallback_type
                actor = first(item, "actor", "role", "agentRole", "fromRole", "source") or fallback_actor
                added += add_event(
                    db, dispatch, runtime,
                    source=f"{collection}:{item_id}:{occurred or ''}",
                    event_type=kind,
                    actor=actor,
                    message=event_message(item, fallback_type),
                    payload=item,
                    occurred_at=occurred,
                    severity=first(item, "level", "severity"),
                    seen=seen,
                )

    elif platform == "hermes":
        status = first(raw, "status", "state")
        updated = first(raw, "updated_at", "updatedAt", "completed_at", "created_at")
        if status:
            added += add_event(
                db, dispatch, runtime,
                source="run-status",
                event_type=f"RUN_{status}",
                actor="Hermes Agent",
                message=f"Hermes run is {status}.",
                payload={"status": status},
                occurred_at=updated,
                seen=seen,
            )
        last_event = raw.get("last_event") or raw.get("event")
        if last_event not in (None, ""):
            kind = first(last_event, "type", "event", "name") if isinstance(last_event, dict) else last_event
            actor = first(last_event, "actor", "tool", "agent") if isinstance(last_event, dict) else "Hermes Agent"
            occurred = first(last_event, "created_at", "createdAt", "timestamp") if isinstance(last_event, dict) else updated
            added += add_event(
                db, dispatch, runtime,
                source=f"last-event:{kind}",
                event_type=kind,
                actor=actor or "Hermes Agent",
                message=event_message(last_event, str(kind)),
                payload=last_event if isinstance(last_event, dict) else {"event": last_event},
                occurred_at=occurred,
                seen=seen,
            )
        approval = raw.get("pending_approval") or raw.get("approval_request") or raw.get("approval")
        if approval:
            added += add_event(
                db, dispatch, runtime,
                source="approval",
                event_type="APPROVAL_REQUIRED",
                actor="Hermes Agent",
                message=event_message(approval, "Hermes is waiting for a tool approval."),
                payload=approval if isinstance(approval, dict) else {"approval": approval},
                occurred_at=updated,
                severity="WARNING",
                seen=seen,
            )
        output = first(raw, "output", "summary", "final_response")
        if output not in (None, "") and normalize_remote_status(status) == "COMPLETED":
            added += add_event(
                db, dispatch, runtime,
                source="result",
                event_type="RESULT_RECEIVED",
                actor="Hermes Agent",
                message=str(output)[:1000],
                payload={"output": str(output)[:9000]},
                occurred_at=updated,
                seen=seen,
            )
        usage = raw.get("usage")
        if isinstance(usage, dict) and usage and normalize_remote_status(status) == "COMPLETED":
            added += add_event(
                db, dispatch, runtime,
                source="usage",
                event_type="USAGE_REPORTED",
                actor="Hermes Agent",
                message="Hermes reported final token usage.",
                payload=usage,
                occurred_at=updated,
                seen=seen,
            )
    return added


remove_route("/api/runtime-dispatches/{dispatch_key}/sync", "POST")


@app.post(
    "/api/runtime-dispatches/{dispatch_key}/sync",
    dependencies=[Depends(require_token)],
)
async def sync_runtime_dispatch_phase3(
    dispatch_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    dispatch, runtime, mission = get_dispatch_bundle(db, dispatch_key)
    if not dispatch.remote_id:
        raise HTTPException(status_code=409, detail="Dispatch has no remote run ID")
    lock_key = f"beezaoffice:dispatch-sync:{dispatch.dispatch_key}"
    if not redis_client.set(lock_key, "1", nx=True, ex=15):
        return phase2_dispatch_view(dispatch)

    previous_status = dispatch.status
    try:
        result = await get_runtime_status(runtime_config(runtime), dispatch.remote_id)
        raw = result.get("raw") or {}
        remote_status = result.get("status")
        remote_output = result.get("output")
        remote_last_event = result.get("last_event")
        if runtime.platform.lower() == "cherryagent" and isinstance(raw, dict):
            run = raw.get("run") if isinstance(raw.get("run"), dict) else raw
            remote_status = first(run, "status", "state") or remote_status
            remote_output = first(run, "output", "summary", "result", "final_response") or remote_output
            remote_last_event = first(run, "lastEvent", "last_event", "event") or remote_last_event

        dispatch.status = normalize_remote_status(remote_status)
        captured = ingest_snapshot(db, dispatch, runtime, raw)
        output = dict(dispatch.output or {})
        if remote_output not in (None, ""):
            output["summary"] = str(remote_output)[:5000]
        output["latency_ms"] = result.get("latency_ms")
        output["last_event"] = remote_last_event
        output["last_sync_at"] = utcnow().isoformat()
        output["runtime_events_captured"] = int(output.get("runtime_events_captured") or 0) + captured
        output["remote"] = bounded_payload(raw)
        dispatch.output = output
        dispatch.error = None
        dispatch.updated_at = utcnow()
        runtime.status = "ONLINE"
        runtime.last_latency_ms = result.get("latency_ms")
        runtime.last_error = None
        runtime.last_probe_at = utcnow()
        update_mission_from_dispatch(mission, runtime, dispatch)
        if dispatch.status != previous_status:
            add_mission_event(
                db,
                mission.mission_key,
                runtime.display_name,
                "RUNTIME_STATUS_CHANGED",
                f"Dispatch {dispatch.dispatch_key} changed from {previous_status} to {dispatch.status}.",
            )
        db.commit()
        db.refresh(dispatch)
        return phase2_dispatch_view(dispatch)
    except RuntimeAdapterError as exc:
        dispatch.error = str(exc)[:1200]
        dispatch.updated_at = utcnow()
        runtime.last_error = str(exc)[:800]
        runtime.last_probe_at = utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        redis_client.delete(lock_key)


ACTIVE_STATUSES = {"DISPATCHING", "STARTED", "RUNNING", "QUEUED", "WAITING_APPROVAL", "STOPPING"}
SYNC_INTERVAL = max(2.0, float(os.getenv("BEEZA_RUNTIME_SYNC_INTERVAL_SECONDS", "5")))
SYNC_BATCH = max(1, min(500, int(os.getenv("BEEZA_RUNTIME_SYNC_BATCH_SIZE", "100"))))
SYNC_CONCURRENCY = max(1, min(32, int(os.getenv("BEEZA_RUNTIME_SYNC_CONCURRENCY", "8"))))
_worker_task: asyncio.Task[None] | None = None


async def sync_one(dispatch_key: str, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        with SessionLocal() as db:
            try:
                await sync_runtime_dispatch_phase3(dispatch_key, db)
            except HTTPException as exc:
                redis_client.hset("beezaoffice:runtime-event-worker:last-errors", dispatch_key, str(exc.detail)[:500])
            except Exception as exc:  # pragma: no cover
                redis_client.hset("beezaoffice:runtime-event-worker:last-errors", dispatch_key, str(exc)[:500])


async def runtime_event_worker() -> None:
    semaphore = asyncio.Semaphore(SYNC_CONCURRENCY)
    while True:
        try:
            with SessionLocal() as db:
                keys = list(
                    db.scalars(
                        select(RuntimeDispatch.dispatch_key)
                        .where(
                            RuntimeDispatch.remote_id.is_not(None),
                            RuntimeDispatch.runtime_key.in_(["cherryagent", "hermes"]),
                            RuntimeDispatch.status.in_(ACTIVE_STATUSES),
                        )
                        .order_by(RuntimeDispatch.updated_at)
                        .limit(SYNC_BATCH)
                    ).all()
                )
            if keys:
                await asyncio.gather(*(sync_one(key, semaphore) for key in keys))
            redis_client.hset(
                "beezaoffice:runtime-event-worker",
                mapping={
                    "status": "online",
                    "last_tick_at": utcnow().isoformat(),
                    "last_batch": str(len(keys)),
                    "interval_seconds": str(SYNC_INTERVAL),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset(
                "beezaoffice:runtime-event-worker",
                mapping={"status": "degraded", "last_tick_at": utcnow().isoformat(), "last_error": str(exc)[:500]},
            )
        await asyncio.sleep(SYNC_INTERVAL)


@app.on_event("startup")
async def start_runtime_event_worker() -> None:
    global _worker_task
    if os.getenv("BEEZA_RUNTIME_SYNC_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        redis_client.hset("beezaoffice:runtime-event-worker", mapping={"status": "disabled"})
        return
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(runtime_event_worker(), name="beeza-runtime-event-worker")


@app.on_event("shutdown")
async def stop_runtime_event_worker() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _worker_task
    _worker_task = None


@app.get("/api/runtime-event-worker")
def runtime_event_worker_status() -> dict[str, Any]:
    state = redis_client.hgetall("beezaoffice:runtime-event-worker")
    return {
        "status": state.get("status", "starting"),
        "last_tick_at": state.get("last_tick_at"),
        "last_batch": int(state.get("last_batch", "0") or 0),
        "interval_seconds": float(state.get("interval_seconds", str(SYNC_INTERVAL))),
    }


@app.get("/api/missions/{mission_key}/runtime-events")
def list_runtime_events(
    mission_key: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=1000),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    if db.scalar(select(Mission.id).where(Mission.mission_key == mission_key)) is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    rows = db.scalars(
        select(RuntimeEvent)
        .where(RuntimeEvent.mission_key == mission_key, RuntimeEvent.id > after_id)
        .order_by(RuntimeEvent.id)
        .limit(limit)
    ).all()
    return [event_view(row) for row in rows]


@app.get("/api/missions/{mission_key}/runtime-events/stream")
async def stream_runtime_events(
    mission_key: str,
    request: Request,
    after_id: int = Query(default=0, ge=0),
) -> StreamingResponse:
    with SessionLocal() as db:
        if db.scalar(select(Mission.id).where(Mission.mission_key == mission_key)) is None:
            raise HTTPException(status_code=404, detail="Mission not found")
    try:
        cursor = max(after_id, int(request.headers.get("last-event-id") or 0))
    except ValueError:
        cursor = after_id

    async def generate() -> AsyncIterator[str]:
        nonlocal cursor
        heartbeat = asyncio.get_running_loop().time()
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            with SessionLocal() as db:
                rows = db.scalars(
                    select(RuntimeEvent)
                    .where(RuntimeEvent.mission_key == mission_key, RuntimeEvent.id > cursor)
                    .order_by(RuntimeEvent.id)
                    .limit(200)
                ).all()
            if rows:
                for row in rows:
                    cursor = row.id
                    payload = json.dumps(event_view(row), ensure_ascii=False, default=str)
                    yield f"id: {row.id}\nevent: runtime.event\ndata: {payload}\n\n"
                heartbeat = asyncio.get_running_loop().time()
            elif asyncio.get_running_loop().time() - heartbeat >= 15:
                yield f"event: heartbeat\ndata: {json.dumps({'at': utcnow().isoformat()})}\n\n"
                heartbeat = asyncio.get_running_loop().time()
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
