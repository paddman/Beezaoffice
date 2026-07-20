from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from main import (
    Mission,
    MissionEvent,
    RuntimeConnector,
    RuntimeDispatch,
    app,
    bounded_payload,
    db_session,
    redis_client,
    require_token,
    runtime_config,
    utcnow,
)
from runtime_adapters import (
    RuntimeAdapterError,
    approve_runtime_run,
    get_runtime_status,
    stop_runtime_run,
)

app.version = "0.3.0"


class RuntimeApprovalCreate(BaseModel):
    choice: str = Field(pattern="^(once|session|always|deny)$")


def normalize_remote_status(value: Any) -> str:
    status = str(value or "UNKNOWN").strip().upper().replace("-", "_").replace(" ", "_")
    if status in {"STARTED", "QUEUED", "RUNNING", "IN_PROGRESS", "WORKING", "ACTIVE"}:
        return "RUNNING"
    if status in {"WAITING_APPROVAL", "AWAITING_APPROVAL", "APPROVAL_REQUIRED", "PENDING_APPROVAL"}:
        return "WAITING_APPROVAL"
    if status in {"COMPLETED", "SUCCEEDED", "SUCCESS", "DONE", "FINISHED"}:
        return "COMPLETED"
    if status in {"FAILED", "ERROR"}:
        return "FAILED"
    if status in {"CANCELLED", "CANCELED", "STOPPED"}:
        return "CANCELLED"
    if status in {"STOPPING", "CANCELLING", "CANCELING"}:
        return "STOPPING"
    return status


def phase2_dispatch_view(row: RuntimeDispatch) -> dict[str, Any]:
    active = row.status in {
        "DISPATCHING",
        "STARTED",
        "RUNNING",
        "QUEUED",
        "WAITING_APPROVAL",
        "STOPPING",
    }
    return {
        "key": row.dispatch_key,
        "runtime_key": row.runtime_key,
        "mission_key": row.mission_key,
        "remote_id": row.remote_id,
        "status": row.status,
        "output": row.output,
        "error": row.error,
        "can_sync": bool(row.remote_id and row.runtime_key in {"cherryagent", "hermes"}),
        "can_stop": bool(active and row.remote_id and row.runtime_key == "hermes"),
        "can_approve": bool(
            row.status == "WAITING_APPROVAL"
            and row.remote_id
            and row.runtime_key == "hermes"
        ),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def add_mission_event(
    db: Session,
    mission_key: str,
    actor: str,
    event_type: str,
    message: str,
) -> None:
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor=actor,
            event_type=event_type,
            message=message[:800],
            created_at=utcnow(),
        )
    )


def update_mission_from_dispatch(
    mission: Mission,
    runtime: RuntimeConnector,
    dispatch: RuntimeDispatch,
) -> None:
    if dispatch.status == "RUNNING":
        mission.status = "EXECUTING"
        mission.progress = max(mission.progress, 20)
        mission.waiting_for = (
            f"{runtime.display_name} run {dispatch.remote_id or dispatch.dispatch_key}"
        )
    elif dispatch.status == "WAITING_APPROVAL":
        mission.status = "WAITING_APPROVAL"
        mission.progress = max(mission.progress, 45)
        mission.waiting_for = f"Human approval requested by {runtime.display_name}"
    elif dispatch.status == "COMPLETED":
        mission.status = "VERIFYING"
        mission.progress = max(mission.progress, 85)
        mission.waiting_for = (
            f"{runtime.display_name} completed; awaiting Beeza verification"
        )
    elif dispatch.status in {"FAILED", "CANCELLED"}:
        mission.status = "BLOCKED"
        mission.waiting_for = f"{runtime.display_name} run {dispatch.status.lower()}"
    elif dispatch.status == "STOPPING":
        mission.waiting_for = f"Waiting for {runtime.display_name} to stop safely"


def get_dispatch_bundle(
    db: Session,
    dispatch_key: str,
) -> tuple[RuntimeDispatch, RuntimeConnector, Mission]:
    dispatch = db.scalar(
        select(RuntimeDispatch).where(RuntimeDispatch.dispatch_key == dispatch_key)
    )
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    runtime = db.scalar(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key == dispatch.runtime_key
        )
    )
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == dispatch.mission_key)
    )
    if not runtime or not mission:
        raise HTTPException(
            status_code=409,
            detail="Dispatch references missing runtime or mission",
        )
    return dispatch, runtime, mission


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


remove_route("/api/missions/{mission_key}", "GET")
remove_route("/api/runtime-dispatches", "GET")


@app.get("/api/missions/{mission_key}")
def mission_detail_phase2(
    mission_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == mission_key)
    )
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    events = db.scalars(
        select(MissionEvent)
        .where(MissionEvent.mission_key == mission_key)
        .order_by(MissionEvent.id)
    ).all()
    dispatches = db.scalars(
        select(RuntimeDispatch)
        .where(RuntimeDispatch.mission_key == mission_key)
        .order_by(RuntimeDispatch.created_at.desc())
    ).all()
    return {
        "key": mission.mission_key,
        "title": mission.title,
        "commander": mission.commander,
        "status": mission.status,
        "priority": mission.priority,
        "progress": mission.progress,
        "waiting_for": mission.waiting_for,
        "objective": mission.objective,
        "events": [
            {
                "actor": event.actor,
                "type": event.event_type,
                "message": event.message,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "dispatches": [phase2_dispatch_view(row) for row in dispatches],
    }


@app.get("/api/runtime-dispatches")
def list_runtime_dispatches_phase2(
    mission_key: str | None = None,
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(RuntimeDispatch)
    if mission_key:
        statement = statement.where(RuntimeDispatch.mission_key == mission_key)
    rows = db.scalars(
        statement.order_by(RuntimeDispatch.created_at.desc()).limit(100)
    ).all()
    return [phase2_dispatch_view(row) for row in rows]


@app.get("/api/runtime-dispatches/{dispatch_key}")
def get_runtime_dispatch_phase2(
    dispatch_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    dispatch, _, _ = get_dispatch_bundle(db, dispatch_key)
    return phase2_dispatch_view(dispatch)


@app.post(
    "/api/runtime-dispatches/{dispatch_key}/sync",
    dependencies=[Depends(require_token)],
)
async def sync_runtime_dispatch(
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
        result = await get_runtime_status(
            runtime_config(runtime),
            dispatch.remote_id,
        )
        dispatch.status = normalize_remote_status(result.get("status"))
        current_output = dict(dispatch.output or {})
        if result.get("output") not in (None, ""):
            current_output["summary"] = str(result.get("output"))[:5000]
        current_output["latency_ms"] = result.get("latency_ms")
        current_output["last_event"] = result.get("last_event")
        current_output["last_sync_at"] = utcnow().isoformat()
        current_output["remote"] = bounded_payload(result.get("raw") or {})
        dispatch.output = current_output
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
                (
                    f"Dispatch {dispatch.dispatch_key} changed from "
                    f"{previous_status} to {dispatch.status}."
                ),
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


@app.post(
    "/api/runtime-dispatches/{dispatch_key}/stop",
    dependencies=[Depends(require_token)],
)
async def stop_runtime_dispatch(
    dispatch_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    dispatch, runtime, mission = get_dispatch_bundle(db, dispatch_key)
    if not dispatch.remote_id:
        raise HTTPException(status_code=409, detail="Dispatch has no remote run ID")
    try:
        result = await stop_runtime_run(
            runtime_config(runtime),
            dispatch.remote_id,
        )
        dispatch.status = normalize_remote_status(
            result.get("status") or "STOPPING"
        )
        current_output = dict(dispatch.output or {})
        current_output["control_latency_ms"] = result.get("latency_ms")
        current_output["last_control"] = "stop"
        current_output["last_sync_at"] = utcnow().isoformat()
        dispatch.output = current_output
        dispatch.updated_at = utcnow()
        update_mission_from_dispatch(mission, runtime, dispatch)
        add_mission_event(
            db,
            mission.mission_key,
            "Beeza Operator",
            "RUNTIME_STOP_REQUESTED",
            (
                f"Requested a safe stop for {runtime.display_name} "
                f"dispatch {dispatch.dispatch_key}."
            ),
        )
        db.commit()
        db.refresh(dispatch)
        return phase2_dispatch_view(dispatch)
    except RuntimeAdapterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/runtime-dispatches/{dispatch_key}/approval",
    dependencies=[Depends(require_token)],
)
async def approve_runtime_dispatch(
    dispatch_key: str,
    payload: RuntimeApprovalCreate,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    dispatch, runtime, mission = get_dispatch_bundle(db, dispatch_key)
    if not dispatch.remote_id:
        raise HTTPException(status_code=409, detail="Dispatch has no remote run ID")
    try:
        result = await approve_runtime_run(
            runtime_config(runtime),
            dispatch.remote_id,
            payload.choice,
        )
        dispatch.status = normalize_remote_status(
            result.get("status") or "RUNNING"
        )
        current_output = dict(dispatch.output or {})
        current_output["control_latency_ms"] = result.get("latency_ms")
        current_output["last_control"] = f"approval:{payload.choice}"
        current_output["last_sync_at"] = utcnow().isoformat()
        dispatch.output = current_output
        dispatch.updated_at = utcnow()
        update_mission_from_dispatch(mission, runtime, dispatch)
        add_mission_event(
            db,
            mission.mission_key,
            "Beeza Operator",
            "RUNTIME_APPROVAL_RESOLVED",
            (
                f"Resolved {runtime.display_name} approval for dispatch "
                f"{dispatch.dispatch_key} with choice {payload.choice}."
            ),
        )
        db.commit()
        db.refresh(dispatch)
        return phase2_dispatch_view(dispatch)
    except RuntimeAdapterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
