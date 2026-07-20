from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase4_app  # noqa: F401 — install Phase 1–4 models, routes, and workers
from collaboration_models import CollaborationTask
from collaboration_service import dispatch_task
from main import (
    Mission,
    MissionEvent,
    RuntimeConnector,
    app,
    db_session,
    redis_client,
    require_token,
    utcnow,
)
from meeting_models import (
    DECISION_STATUSES,
    MEETING_STATUSES,
    Meeting,
    MeetingCreate,
    MeetingDecision,
    MeetingDecisionCreate,
    MeetingParticipant,
    MeetingTurn,
    decision_view,
    meeting_view,
    participant_view,
    turn_view,
)
from meeting_service import (
    MEETING_INTERVAL,
    MEETING_TURN_TIMEOUT_SECONDS,
    create_action_task,
    create_round,
    decisions_for,
    get_meeting,
    meeting_event,
    meeting_tick,
    meeting_worker,
    participants_for,
    process_meeting,
    turns_for,
)

app.version = "0.6.0"
_meeting_worker_task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def start_meeting_worker() -> None:
    global _meeting_worker_task
    if os.getenv("BEEZA_MEETING_ENABLED", "true").lower() in {
        "0", "false", "no", "off",
    }:
        redis_client.hset("beezaoffice:meeting-worker", mapping={"status": "disabled"})
        return
    if _meeting_worker_task is None or _meeting_worker_task.done():
        _meeting_worker_task = asyncio.create_task(
            meeting_worker(), name="beeza-meeting-worker"
        )


@app.on_event("shutdown")
async def stop_meeting_worker() -> None:
    global _meeting_worker_task
    if _meeting_worker_task is None:
        return
    _meeting_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _meeting_worker_task
    _meeting_worker_task = None


def meeting_detail_payload(db: Session, meeting: Meeting) -> dict[str, Any]:
    participants = participants_for(db, meeting.meeting_key)
    turns = turns_for(db, meeting.meeting_key)
    decisions = decisions_for(db, meeting.meeting_key)
    active_turn = next(
        (
            row
            for row in turns
            if row.status in {"QUEUED", "DISPATCHING", "RUNNING"}
        ),
        None,
    )
    return {
        **meeting_view(meeting),
        "participants": [participant_view(row) for row in participants],
        "turns": [turn_view(row) for row in turns],
        "decisions": [decision_view(row) for row in decisions],
        "active_turn_key": active_turn.turn_key if active_turn else None,
        "stats": {
            "participants": len(participants),
            "turns": len(turns),
            "completed_turns": sum(row.status == "COMPLETED" for row in turns),
            "failed_turns": sum(row.status == "FAILED" for row in turns),
            "decisions": len(decisions),
        },
    }


@app.get("/api/meeting-worker")
def meeting_worker_status() -> dict[str, Any]:
    state = redis_client.hgetall("beezaoffice:meeting-worker")
    return {
        "status": state.get("status", "starting"),
        "last_tick_at": state.get("last_tick_at"),
        "last_processed": int(state.get("last_processed", "0") or 0),
        "interval_seconds": float(
            state.get("interval_seconds", str(MEETING_INTERVAL))
        ),
        "turn_timeout_seconds": MEETING_TURN_TIMEOUT_SECONDS,
        "last_error": state.get("last_error"),
    }


@app.post("/api/meeting-worker/tick", dependencies=[Depends(require_token)])
async def run_meeting_worker_tick() -> dict[str, Any]:
    return {"ok": True, **(await meeting_tick())}


@app.get("/api/missions/{mission_key}/meetings")
def list_mission_meetings(
    mission_key: str,
    status: str | None = Query(default=None),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    if db.scalar(select(Mission.id).where(Mission.mission_key == mission_key)) is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    statement = select(Meeting).where(Meeting.mission_key == mission_key)
    if status:
        normalized = status.upper()
        if normalized not in MEETING_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown meeting status")
        statement = statement.where(Meeting.status == normalized)
    rows = db.scalars(statement.order_by(Meeting.created_at.desc())).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        participant_count = db.scalar(
            select(MeetingParticipant.id)
            .where(MeetingParticipant.meeting_key == row.meeting_key)
            .limit(1)
        )
        turns = turns_for(db, row.meeting_key)
        result.append(
            {
                **meeting_view(row),
                "participant_count": len(participants_for(db, row.meeting_key))
                if participant_count
                else 0,
                "completed_turns": sum(turn.status == "COMPLETED" for turn in turns),
                "total_turns": len(turns),
            }
        )
    return result


@app.post(
    "/api/missions/{mission_key}/meetings",
    dependencies=[Depends(require_token)],
    status_code=201,
)
def create_meeting(
    mission_key: str,
    payload: MeetingCreate,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    mission = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    if not any(item.role == "MODERATOR" for item in payload.participants):
        raise HTTPException(
            status_code=422,
            detail="At least one MODERATOR participant is required",
        )
    identities = [item.identity.casefold() for item in payload.participants]
    if len(identities) != len(set(identities)):
        raise HTTPException(status_code=422, detail="Participant identities must be unique")
    runtime_keys = list(dict.fromkeys(item.runtime_key for item in payload.participants))
    known = set(
        db.scalars(
            select(RuntimeConnector.runtime_key).where(
                RuntimeConnector.runtime_key.in_(runtime_keys)
            )
        ).all()
    )
    unknown = [key for key in runtime_keys if key not in known]
    if unknown:
        raise HTTPException(
            status_code=409,
            detail=f"Unknown runtimes: {', '.join(unknown)}",
        )

    now = utcnow()
    meeting = Meeting(
        meeting_key=f"MEET-{uuid4().hex[:12].upper()}",
        mission_key=mission_key,
        title=payload.title,
        objective=payload.objective,
        agenda=payload.agenda,
        status="DRAFT",
        current_round=0,
        max_rounds=payload.max_rounds,
        decision_rule=payload.decision_rule,
        moderator_identity=payload.moderator_identity,
        owner_identity=payload.owner_identity,
        summary="",
        started_at=None,
        ended_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(meeting)
    db.flush()
    for order, item in enumerate(payload.participants, start=1):
        db.add(
            MeetingParticipant(
                participant_key=f"PART-{uuid4().hex[:12].upper()}",
                meeting_key=meeting.meeting_key,
                identity=item.identity,
                runtime_key=item.runtime_key,
                role=item.role,
                speaking_order=order,
                required=item.required,
                instructions=item.instructions,
                active=True,
                created_at=now,
            )
        )
    meeting_event(
        db,
        meeting,
        "MEETING_CREATED",
        payload.owner_identity,
        f"Created structured meeting with {len(payload.participants)} participants.",
        {
            "agenda": payload.agenda,
            "max_rounds": payload.max_rounds,
            "decision_rule": payload.decision_rule,
            "participants": [item.model_dump(mode="json") for item in payload.participants],
        },
    )
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor=payload.owner_identity[:80],
            event_type="MEETING_CREATED",
            message=f"Created {meeting.meeting_key}: {meeting.title}"[:800],
            created_at=now,
        )
    )
    db.commit()
    db.refresh(meeting)
    return meeting_detail_payload(db, meeting)


@app.get("/api/meetings/{meeting_key}")
def read_meeting(
    meeting_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_key)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting_detail_payload(db, meeting)


@app.post(
    "/api/meetings/{meeting_key}/start",
    dependencies=[Depends(require_token)],
)
async def start_meeting(
    meeting_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_key)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status not in {"DRAFT", "SCHEDULED"}:
        raise HTTPException(
            status_code=409,
            detail=f"Meeting cannot start from {meeting.status}",
        )
    participants = participants_for(db, meeting_key)
    if len(participants) < 2:
        raise HTTPException(status_code=409, detail="Meeting requires at least two participants")
    required_runtime_keys = {
        item.runtime_key for item in participants if item.required and item.role != "OBSERVER"
    }
    runtimes = db.scalars(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key.in_(required_runtime_keys)
        )
    ).all()
    unavailable = [row.display_name for row in runtimes if not row.base_url]
    missing_runtime_keys = required_runtime_keys - {row.runtime_key for row in runtimes}
    unavailable.extend(sorted(missing_runtime_keys))
    if unavailable:
        raise HTTPException(
            status_code=409,
            detail=f"Required meeting runtimes are not configured: {', '.join(unavailable)}",
        )

    now = utcnow()
    meeting.status = "RUNNING"
    meeting.started_at = now
    meeting.updated_at = now
    create_round(db, meeting, 1)
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == meeting.mission_key)
    )
    if mission:
        mission.status = "EXECUTING"
        mission.waiting_for = f"Structured meeting {meeting.meeting_key} in progress"
        mission.progress = max(mission.progress, 20)
    meeting_event(
        db,
        meeting,
        "MEETING_STARTED",
        meeting.moderator_identity,
        f"Started {meeting.meeting_key}; discussion is bounded to {meeting.max_rounds} rounds.",
        {
            "decision_rule": meeting.decision_rule,
            "max_rounds": meeting.max_rounds,
        },
    )
    db.add(
        MissionEvent(
            mission_key=meeting.mission_key,
            actor=meeting.moderator_identity[:80],
            event_type="MEETING_STARTED",
            message=f"Started {meeting.meeting_key}: {meeting.title}"[:800],
            created_at=now,
        )
    )
    db.commit()
    await process_meeting(meeting_key)
    meeting = get_meeting(db, meeting_key)
    return meeting_detail_payload(db, meeting)


@app.post(
    "/api/meetings/{meeting_key}/tick",
    dependencies=[Depends(require_token)],
)
async def tick_meeting(
    meeting_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_key)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    result = await process_meeting(meeting_key)
    meeting = get_meeting(db, meeting_key)
    return {"result": result, "meeting": meeting_detail_payload(db, meeting)}


@app.post(
    "/api/meetings/{meeting_key}/cancel",
    dependencies=[Depends(require_token)],
)
def cancel_meeting(
    meeting_key: str,
    note: str = Query(default="Cancelled by operator", max_length=2000),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_key)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"Meeting is already {meeting.status}")
    now = utcnow()
    meeting.status = "CANCELLED"
    meeting.ended_at = now
    meeting.updated_at = now
    for turn in turns_for(db, meeting_key):
        if turn.status in {"QUEUED", "DISPATCHING", "RUNNING"}:
            turn.status = "SKIPPED"
            turn.completed_at = now
            turn.updated_at = now
    meeting_event(
        db,
        meeting,
        "MEETING_CANCELLED",
        "Beeza Operator",
        note,
        {},
        "WARNING",
    )
    db.add(
        MissionEvent(
            mission_key=meeting.mission_key,
            actor="Beeza Operator",
            event_type="MEETING_CANCELLED",
            message=f"{meeting.meeting_key}: {note}"[:800],
            created_at=now,
        )
    )
    db.commit()
    db.refresh(meeting)
    return meeting_detail_payload(db, meeting)


@app.post(
    "/api/meetings/{meeting_key}/decision",
    dependencies=[Depends(require_token)],
    status_code=201,
)
async def decide_meeting(
    meeting_key: str,
    payload: MeetingDecisionCreate,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    meeting = get_meeting(db, meeting_key)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if payload.status not in DECISION_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown decision status")
    if meeting.status not in {"RUNNING", "AWAITING_DECISION"}:
        raise HTTPException(
            status_code=409,
            detail=f"Meeting cannot be decided from {meeting.status}",
        )

    action_runtime_keys = list(
        dict.fromkeys(item.target_runtime_key for item in payload.action_items)
    )
    if action_runtime_keys:
        known = set(
            db.scalars(
                select(RuntimeConnector.runtime_key).where(
                    RuntimeConnector.runtime_key.in_(action_runtime_keys)
                )
            ).all()
        )
        unknown = [key for key in action_runtime_keys if key not in known]
        if unknown:
            raise HTTPException(
                status_code=409,
                detail=f"Unknown action-item runtimes: {', '.join(unknown)}",
            )

    now = utcnow()
    decision = MeetingDecision(
        decision_key=f"DEC-{uuid4().hex[:12].upper()}",
        meeting_key=meeting_key,
        title=payload.title,
        rationale=payload.rationale,
        status=payload.status,
        decided_by=payload.decided_by,
        confidence=payload.confidence,
        votes=payload.votes,
        action_items=[item.model_dump(mode="json") for item in payload.action_items],
        generated_task_keys=[],
        created_at=now,
        updated_at=now,
    )
    db.add(decision)
    db.flush()

    created_tasks: list[CollaborationTask] = []
    if payload.status in {"ACCEPTED", "OVERRIDDEN"}:
        for item in payload.action_items:
            created_tasks.append(create_action_task(db, meeting, decision, item))
        decision.generated_task_keys = [task.task_key for task in created_tasks]

    for turn in turns_for(db, meeting_key):
        if turn.status in {"QUEUED", "DISPATCHING", "RUNNING"}:
            turn.status = "SKIPPED"
            turn.completed_at = now
            turn.updated_at = now

    meeting.status = "COMPLETED"
    meeting.ended_at = now
    meeting.updated_at = now
    decision_line = (
        f"Decision {payload.status}: {payload.title}\n"
        f"Confidence: {payload.confidence:.2f}\n"
        f"Rationale: {payload.rationale}"
    )
    meeting.summary = (
        f"{meeting.summary}\n\n{decision_line}" if meeting.summary else decision_line
    )[:6000]
    severity = "WARNING" if payload.status == "OVERRIDDEN" else "INFO"
    meeting_event(
        db,
        meeting,
        f"MEETING_DECISION_{payload.status}",
        payload.decided_by,
        payload.rationale,
        {
            "decision_key": decision.decision_key,
            "title": payload.title,
            "confidence": payload.confidence,
            "votes": payload.votes,
            "generated_task_keys": decision.generated_task_keys,
        },
        severity,
    )
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == meeting.mission_key)
    )
    if mission:
        mission.waiting_for = (
            f"Decision produced {len(created_tasks)} action items"
            if created_tasks
            else "Meeting decision recorded"
        )
        mission.progress = max(mission.progress, 35)
    db.add(
        MissionEvent(
            mission_key=meeting.mission_key,
            actor=payload.decided_by[:80],
            event_type=f"MEETING_DECISION_{payload.status}",
            message=(
                f"{meeting.meeting_key}: {payload.title}; "
                f"created {len(created_tasks)} action items."
            )[:800],
            created_at=now,
        )
    )
    db.commit()

    for task_key in decision.generated_task_keys:
        task = db.scalar(
            select(CollaborationTask).where(
                CollaborationTask.task_key == task_key
            )
        )
        if task is not None and task.status == "QUEUED" and task.auto_dispatch:
            await dispatch_task(db, task)

    db.refresh(meeting)
    db.refresh(decision)
    return meeting_detail_payload(db, meeting)
