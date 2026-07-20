from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask, aware
from collaboration_service import collaboration_event, create_message
from main import (
    Mission,
    MissionEvent,
    RuntimeConnector,
    RuntimeDispatch,
    SessionLocal,
    bounded_payload,
    redis_client,
    runtime_config,
    utcnow,
)
from meeting_models import (
    Meeting,
    MeetingActionItemCreate,
    MeetingDecision,
    MeetingParticipant,
    MeetingTurn,
)
from phase2_app import normalize_remote_status
from phase3_app import RuntimeEvent
from runtime_adapters import RuntimeAdapterError, dispatch_runtime

MEETING_INTERVAL = max(2.0, float(os.getenv("BEEZA_MEETING_INTERVAL_SECONDS", "3")))
MEETING_BATCH = max(1, min(200, int(os.getenv("BEEZA_MEETING_BATCH_SIZE", "50"))))
MEETING_TURN_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("BEEZA_MEETING_TURN_TIMEOUT_SECONDS", "900")),
)


def meeting_event(
    db: Session,
    meeting: Meeting,
    event_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any] | None = None,
    severity: str = "INFO",
    dispatch_key: str | None = None,
) -> None:
    body = bounded_payload(payload or {})
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{meeting.meeting_key}|{event_type}|{meeting.status}|{message}|{encoded}".encode()
    ).hexdigest()[:40]
    key = f"meeting:{meeting.meeting_key}:{event_type}:{digest}"[:180]
    if db.scalar(select(RuntimeEvent.id).where(RuntimeEvent.event_key == key)):
        return
    now = utcnow()
    db.add(
        RuntimeEvent(
            event_key=key,
            mission_key=meeting.mission_key,
            dispatch_key=dispatch_key or meeting.meeting_key,
            runtime_key="beeza-meeting",
            event_type=event_type,
            actor=actor[:120],
            message=message[:1000],
            severity=severity,
            payload=body if isinstance(body, dict) else {"value": body},
            occurred_at=now,
            created_at=now,
        )
    )


def get_meeting(db: Session, meeting_key: str) -> Meeting | None:
    return db.scalar(select(Meeting).where(Meeting.meeting_key == meeting_key))


def participants_for(db: Session, meeting_key: str) -> list[MeetingParticipant]:
    return list(
        db.scalars(
            select(MeetingParticipant)
            .where(
                MeetingParticipant.meeting_key == meeting_key,
                MeetingParticipant.active.is_(True),
            )
            .order_by(MeetingParticipant.speaking_order)
        ).all()
    )


def turns_for(db: Session, meeting_key: str) -> list[MeetingTurn]:
    return list(
        db.scalars(
            select(MeetingTurn)
            .where(MeetingTurn.meeting_key == meeting_key)
            .order_by(MeetingTurn.round_number, MeetingTurn.speaking_order)
        ).all()
    )


def decisions_for(db: Session, meeting_key: str) -> list[MeetingDecision]:
    return list(
        db.scalars(
            select(MeetingDecision)
            .where(MeetingDecision.meeting_key == meeting_key)
            .order_by(MeetingDecision.created_at)
        ).all()
    )


def participant_by_key(db: Session, participant_key: str) -> MeetingParticipant | None:
    return db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.participant_key == participant_key
        )
    )


def create_round(db: Session, meeting: Meeting, round_number: int) -> int:
    existing = db.scalar(
        select(MeetingTurn.id).where(
            MeetingTurn.meeting_key == meeting.meeting_key,
            MeetingTurn.round_number == round_number,
        )
    )
    if existing:
        return 0
    participants = participants_for(db, meeting.meeting_key)
    now = utcnow()
    created = 0
    for participant in participants:
        if participant.role == "OBSERVER":
            continue
        db.add(
            MeetingTurn(
                turn_key=f"TURN-{uuid4().hex[:12].upper()}",
                meeting_key=meeting.meeting_key,
                participant_key=participant.participant_key,
                round_number=round_number,
                speaking_order=participant.speaking_order,
                status="QUEUED",
                prompt="",
                contribution={},
                confidence=None,
                created_at=now,
                updated_at=now,
            )
        )
        created += 1
    meeting.current_round = round_number
    meeting.updated_at = now
    meeting_event(
        db,
        meeting,
        "MEETING_ROUND_OPENED",
        meeting.moderator_identity,
        f"Opened meeting round {round_number} with {created} speaking turns.",
        {"round": round_number, "turns": created},
    )
    return created


def prior_contributions(db: Session, meeting: Meeting, limit: int = 12) -> str:
    rows = list(
        db.scalars(
            select(MeetingTurn)
            .where(
                MeetingTurn.meeting_key == meeting.meeting_key,
                MeetingTurn.status == "COMPLETED",
            )
            .order_by(MeetingTurn.round_number.desc(), MeetingTurn.speaking_order.desc())
            .limit(limit)
        ).all()
    )
    if not rows:
        return "No prior contributions."
    rows.reverse()
    parts: list[str] = []
    for turn in rows:
        participant = participant_by_key(db, turn.participant_key)
        identity = participant.identity if participant else turn.participant_key
        summary = str((turn.contribution or {}).get("summary") or "")[:1200]
        if summary:
            parts.append(f"- {identity} (round {turn.round_number}): {summary}")
    return "\n".join(parts) or "No prior contributions."


def turn_prompt(
    db: Session,
    meeting: Meeting,
    participant: MeetingParticipant,
    turn: MeetingTurn,
) -> str:
    agenda = "\n".join(f"- {item}" for item in meeting.agenda or []) or "- Resolve the stated objective"
    previous = prior_contributions(db, meeting)
    role_guidance = {
        "MODERATOR": "Frame the discussion, identify disagreements, and keep the group on the agenda.",
        "EXECUTIVE": "Evaluate options against business outcome, risk, timing, and organizational constraints.",
        "DOMAIN": "Provide domain analysis, evidence, feasible options, and implementation constraints.",
        "CRITIC": "Challenge assumptions, identify failure modes, and state what evidence is still missing.",
        "PMO": "Translate accepted direction into owners, deliverables, dependencies, and deadlines.",
    }.get(participant.role, "Contribute only information relevant to the objective.")
    return (
        f"BeezaOffice structured meeting {meeting.meeting_key}\n"
        f"Mission: {meeting.mission_key}\n"
        f"Meeting: {meeting.title}\n"
        f"Objective: {meeting.objective}\n"
        f"Decision rule: {meeting.decision_rule}\n"
        f"Round: {turn.round_number}/{meeting.max_rounds}\n"
        f"Your identity: {participant.identity}\n"
        f"Your role: {participant.role}\n\n"
        f"Agenda:\n{agenda}\n\n"
        f"Prior contributions:\n{previous}\n\n"
        f"Role instruction: {role_guidance}\n"
        f"Participant instruction: {participant.instructions or 'No additional instruction.'}\n\n"
        "Rules:\n"
        "- Do not repeat an earlier point unless correcting it or adding evidence.\n"
        "- Be concise and name assumptions, risks, blockers, and recommended option.\n"
        "- End with a confidence value from 0.00 to 1.00.\n"
        "- Return JSON when possible: summary, recommendation, evidence, risks, blockers, confidence.\n"
        "- Do not execute consequential actions; this meeting produces advice and decisions only."
    )[:8000]


def parse_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if 0 <= numeric <= 1:
            return numeric
        if 1 < numeric <= 100:
            return numeric / 100
    if isinstance(value, str):
        text = value.strip()
        percent = re.search(r"confidence\s*[:=]\s*(\d{1,3})\s*%", text, re.I)
        if percent:
            return min(100.0, float(percent.group(1))) / 100
        decimal = re.search(r"confidence\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?)", text, re.I)
        if decimal:
            return float(decimal.group(1))
    return None


def parse_contribution(output: Any) -> tuple[dict[str, Any], float | None]:
    if isinstance(output, dict):
        body = bounded_payload(output)
        if not isinstance(body, dict):
            body = {"summary": str(output)[:5000]}
        confidence = parse_confidence(body.get("confidence"))
        return body, confidence
    text = str(output or "").strip()
    if not text:
        return {}, None
    parsed: Any = None
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    if isinstance(parsed, dict):
        body = bounded_payload(parsed)
        if not isinstance(body, dict):
            body = {"summary": text[:5000]}
        return body, parse_confidence(body.get("confidence") or text)
    return {"summary": text[:5000]}, parse_confidence(text)


def summarize_meeting(db: Session, meeting: Meeting) -> str:
    lines: list[str] = []
    for turn in turns_for(db, meeting.meeting_key):
        if turn.status != "COMPLETED":
            continue
        participant = participant_by_key(db, turn.participant_key)
        identity = participant.identity if participant else turn.participant_key
        summary = str((turn.contribution or {}).get("summary") or "").strip()
        if summary:
            confidence = f" · confidence {turn.confidence:.2f}" if turn.confidence is not None else ""
            lines.append(f"Round {turn.round_number} · {identity}{confidence}: {summary}")
    return "\n".join(lines)[:6000]


def complete_turn(
    db: Session,
    meeting: Meeting,
    turn: MeetingTurn,
    participant: MeetingParticipant,
    output: Any,
) -> None:
    contribution, confidence = parse_contribution(output)
    now = utcnow()
    turn.status = "COMPLETED"
    turn.contribution = contribution
    turn.confidence = confidence
    turn.completed_at = now
    turn.updated_at = now
    meeting.updated_at = now
    summary = str(contribution.get("summary") or "Turn completed")[:800]
    meeting_event(
        db,
        meeting,
        "MEETING_TURN_COMPLETED",
        participant.identity,
        summary,
        {
            "turn_key": turn.turn_key,
            "round": turn.round_number,
            "role": participant.role,
            "confidence": confidence,
            "contribution": contribution,
        },
        dispatch_key=turn.dispatch_key,
    )


async def dispatch_turn(
    db: Session,
    meeting: Meeting,
    turn: MeetingTurn,
) -> None:
    participant = participant_by_key(db, turn.participant_key)
    if participant is None:
        turn.status = "FAILED"
        turn.contribution = {"error": "Meeting participant is missing"}
        turn.updated_at = utcnow()
        return
    runtime = db.scalar(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key == participant.runtime_key
        )
    )
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == meeting.mission_key)
    )
    if runtime is None or mission is None or not runtime.base_url:
        turn.status = "FAILED"
        turn.contribution = {
            "error": "Target runtime or mission is missing or unconfigured"
        }
        turn.updated_at = utcnow()
        meeting_event(
            db,
            meeting,
            "MEETING_TURN_FAILED",
            "Beeza Meeting Manager",
            f"Could not dispatch {participant.identity}; runtime {participant.runtime_key} is unavailable.",
            {"participant": participant.identity, "runtime": participant.runtime_key},
            "ERROR",
        )
        return

    now = utcnow()
    prompt = turn_prompt(db, meeting, participant, turn)
    dispatch = RuntimeDispatch(
        dispatch_key=f"DSP-{uuid4().hex[:12].upper()}",
        runtime_key=runtime.runtime_key,
        mission_key=meeting.mission_key,
        status="DISPATCHING",
        output={"meeting_key": meeting.meeting_key, "meeting_turn_key": turn.turn_key},
        created_at=now,
        updated_at=now,
    )
    db.add(dispatch)
    db.flush()
    turn.prompt = prompt
    turn.dispatch_key = dispatch.dispatch_key
    turn.status = "DISPATCHING"
    turn.started_at = now
    turn.updated_at = now
    meeting.updated_at = now
    meeting_event(
        db,
        meeting,
        "MEETING_TURN_DISPATCHING",
        meeting.moderator_identity,
        f"Invited {participant.identity} to speak in round {turn.round_number}.",
        {
            "turn_key": turn.turn_key,
            "participant": participant.identity,
            "role": participant.role,
            "runtime": participant.runtime_key,
        },
        dispatch_key=dispatch.dispatch_key,
    )
    db.commit()

    package = {
        "mission_key": mission.mission_key,
        "title": f"Meeting turn · {meeting.title}",
        "objective": meeting.objective,
        "priority": mission.priority,
        "prompt": prompt,
        "roles": [],
        "tags": [
            "beeza-meeting",
            meeting.meeting_key,
            turn.turn_key,
            participant.role.lower(),
        ],
        "instructions": (
            "Structured BeezaOffice meeting turn. Discuss only; do not perform "
            "consequential actions. Return a concise evidence-backed contribution."
        ),
    }
    try:
        result = await dispatch_runtime(runtime_config(runtime), package)
        dispatch.remote_id = (
            str(result.get("remote_id")) if result.get("remote_id") else None
        )
        dispatch.status = normalize_remote_status(result.get("status") or "STARTED")
        dispatch.output = {
            "meeting_key": meeting.meeting_key,
            "meeting_turn_key": turn.turn_key,
            "summary": str(result.get("output") or "")[:5000],
            "latency_ms": result.get("latency_ms"),
            "remote": bounded_payload(result.get("raw") or {}),
        }
        dispatch.updated_at = utcnow()
        runtime.status = "ONLINE"
        runtime.last_latency_ms = result.get("latency_ms")
        runtime.last_error = None
        runtime.last_probe_at = utcnow()
        if dispatch.status == "COMPLETED":
            complete_turn(db, meeting, turn, participant, result.get("output"))
        elif dispatch.status in {"FAILED", "CANCELLED"}:
            turn.status = "FAILED"
            turn.contribution = {"error": f"Runtime returned {dispatch.status}"}
            turn.updated_at = utcnow()
        else:
            turn.status = "RUNNING"
            turn.updated_at = utcnow()
    except RuntimeAdapterError as exc:
        dispatch.status = "FAILED"
        dispatch.error = str(exc)[:1200]
        dispatch.updated_at = utcnow()
        runtime.status = "OFFLINE"
        runtime.last_error = str(exc)[:800]
        runtime.last_probe_at = utcnow()
        turn.status = "FAILED"
        turn.contribution = {"error": str(exc)[:1200]}
        turn.completed_at = utcnow()
        turn.updated_at = utcnow()
        meeting_event(
            db,
            meeting,
            "MEETING_TURN_FAILED",
            participant.identity,
            str(exc)[:1000],
            {"turn_key": turn.turn_key, "dispatch_key": dispatch.dispatch_key},
            "ERROR",
            dispatch.dispatch_key,
        )
    db.commit()


def mirror_turn_dispatch(db: Session, meeting: Meeting, turn: MeetingTurn) -> None:
    if not turn.dispatch_key:
        return
    dispatch = db.scalar(
        select(RuntimeDispatch).where(
            RuntimeDispatch.dispatch_key == turn.dispatch_key
        )
    )
    participant = participant_by_key(db, turn.participant_key)
    if dispatch is None or participant is None:
        return
    remote = normalize_remote_status(dispatch.status)
    if remote in {"RUNNING", "WAITING_APPROVAL", "STOPPING"}:
        turn.status = "RUNNING"
        turn.updated_at = utcnow()
        if (
            turn.started_at is not None
            and utcnow() - aware(turn.started_at)
            > timedelta(seconds=MEETING_TURN_TIMEOUT_SECONDS)
        ):
            turn.status = "FAILED"
            turn.completed_at = utcnow()
            turn.contribution = {"error": "Meeting turn exceeded timeout"}
            meeting_event(
                db,
                meeting,
                "MEETING_TURN_TIMEOUT",
                "Beeza Meeting Manager",
                f"Turn {turn.turn_key} for {participant.identity} exceeded the time limit.",
                {"turn_key": turn.turn_key, "dispatch_key": dispatch.dispatch_key},
                "ERROR",
                dispatch.dispatch_key,
            )
        return
    if remote == "COMPLETED":
        output = (dispatch.output or {}).get("summary") or (dispatch.output or {}).get("remote")
        complete_turn(db, meeting, turn, participant, output)
        return
    if remote in {"FAILED", "CANCELLED"}:
        turn.status = "FAILED"
        turn.completed_at = utcnow()
        turn.updated_at = utcnow()
        turn.contribution = {
            "error": dispatch.error or f"Runtime dispatch {remote.lower()}"
        }
        meeting_event(
            db,
            meeting,
            "MEETING_TURN_FAILED",
            participant.identity,
            str(turn.contribution.get("error"))[:1000],
            {"turn_key": turn.turn_key, "dispatch_key": dispatch.dispatch_key},
            "ERROR",
            dispatch.dispatch_key,
        )


async def process_meeting(meeting_key: str) -> dict[str, Any]:
    lock_key = f"beezaoffice:meeting-lock:{meeting_key}"
    if not redis_client.set(lock_key, "1", nx=True, ex=30):
        return {"meeting_key": meeting_key, "action": "locked"}
    try:
        with SessionLocal() as db:
            meeting = get_meeting(db, meeting_key)
            if meeting is None or meeting.status != "RUNNING":
                return {"meeting_key": meeting_key, "action": "inactive"}

            active = db.scalar(
                select(MeetingTurn)
                .where(
                    MeetingTurn.meeting_key == meeting_key,
                    MeetingTurn.status.in_(["DISPATCHING", "RUNNING"]),
                )
                .order_by(MeetingTurn.round_number, MeetingTurn.speaking_order)
            )
            if active is not None:
                previous = active.status
                mirror_turn_dispatch(db, meeting, active)
                db.commit()
                return {
                    "meeting_key": meeting_key,
                    "action": "mirrored",
                    "turn_key": active.turn_key,
                    "from": previous,
                    "to": active.status,
                }

            queued = db.scalar(
                select(MeetingTurn)
                .where(
                    MeetingTurn.meeting_key == meeting_key,
                    MeetingTurn.status == "QUEUED",
                )
                .order_by(MeetingTurn.round_number, MeetingTurn.speaking_order)
            )
            if queued is not None:
                await dispatch_turn(db, meeting, queued)
                return {
                    "meeting_key": meeting_key,
                    "action": "dispatched",
                    "turn_key": queued.turn_key,
                    "status": queued.status,
                }

            if meeting.current_round < meeting.max_rounds:
                created = create_round(db, meeting, meeting.current_round + 1)
                db.commit()
                return {
                    "meeting_key": meeting_key,
                    "action": "round-opened",
                    "round": meeting.current_round,
                    "turns": created,
                }

            meeting.status = "AWAITING_DECISION"
            meeting.summary = summarize_meeting(db, meeting)
            meeting.updated_at = utcnow()
            meeting_event(
                db,
                meeting,
                "MEETING_AWAITING_DECISION",
                meeting.moderator_identity,
                "All bounded discussion rounds are complete; a decision is required.",
                {
                    "rounds": meeting.max_rounds,
                    "decision_rule": meeting.decision_rule,
                },
                "WARNING",
            )
            db.add(
                MissionEvent(
                    mission_key=meeting.mission_key,
                    actor=meeting.moderator_identity[:80],
                    event_type="MEETING_AWAITING_DECISION",
                    message=f"{meeting.meeting_key} completed discussion and requires a decision."[:800],
                    created_at=utcnow(),
                )
            )
            db.commit()
            return {"meeting_key": meeting_key, "action": "awaiting-decision"}
    finally:
        redis_client.delete(lock_key)


async def meeting_tick() -> dict[str, int]:
    with SessionLocal() as db:
        keys = list(
            db.scalars(
                select(Meeting.meeting_key)
                .where(Meeting.status == "RUNNING")
                .order_by(Meeting.updated_at)
                .limit(MEETING_BATCH)
            ).all()
        )
    processed = 0
    for key in keys:
        await process_meeting(key)
        processed += 1
    return {"processed": processed}


async def meeting_worker() -> None:
    while True:
        try:
            result = await meeting_tick()
            redis_client.hset(
                "beezaoffice:meeting-worker",
                mapping={
                    "status": "online",
                    "last_tick_at": utcnow().isoformat(),
                    "last_processed": str(result["processed"]),
                    "interval_seconds": str(MEETING_INTERVAL),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset(
                "beezaoffice:meeting-worker",
                mapping={
                    "status": "degraded",
                    "last_tick_at": utcnow().isoformat(),
                    "last_error": str(exc)[:500],
                },
            )
        await asyncio.sleep(MEETING_INTERVAL)


def create_action_task(
    db: Session,
    meeting: Meeting,
    decision: MeetingDecision,
    item: MeetingActionItemCreate,
) -> CollaborationTask:
    now = utcnow()
    task = CollaborationTask(
        task_key=f"TASK-{uuid4().hex[:12].upper()}",
        mission_key=meeting.mission_key,
        parent_task_key=None,
        title=item.title,
        objective=item.objective,
        source_identity=decision.decided_by,
        target_identity=item.target_identity or f"runtime:{item.target_runtime_key}",
        target_runtime_key=item.target_runtime_key,
        status="QUEUED",
        priority=item.priority,
        review_policy=item.review_policy,
        auto_dispatch=True,
        depends_on=[],
        inputs=[
            {
                "type": "meeting_decision",
                "meeting_key": meeting.meeting_key,
                "decision_key": decision.decision_key,
                "rationale": decision.rationale,
            }
        ],
        expected_outputs=item.expected_outputs,
        acceptance_criteria=item.acceptance_criteria,
        context={
            "meeting_key": meeting.meeting_key,
            "decision_key": decision.decision_key,
            "owner_identity": item.owner_identity or item.target_identity,
        },
        result={},
        dispatch_key=None,
        attempts=0,
        follow_up_count=0,
        last_progress_at=now,
        next_follow_up_at=None,
        deadline_at=aware(item.deadline_at),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    create_message(
        db,
        mission_key=meeting.mission_key,
        task_key=task.task_key,
        message_type="DECISION",
        source_identity=decision.decided_by,
        target_identity=task.target_identity,
        subject=f"Meeting decision action · {task.title}",
        body=task.objective,
        payload={
            "meeting_key": meeting.meeting_key,
            "decision_key": decision.decision_key,
            "confidence": decision.confidence,
            "expected_outputs": task.expected_outputs,
            "acceptance_criteria": task.acceptance_criteria,
        },
        status="DELIVERED",
        reply_required=True,
        due_at=task.deadline_at,
    )
    collaboration_event(
        db,
        task,
        "MEETING_ACTION_CREATED",
        decision.decided_by,
        f"Created {task.task_key} from decision {decision.decision_key}.",
        {
            "meeting_key": meeting.meeting_key,
            "decision_key": decision.decision_key,
            "runtime": task.target_runtime_key,
        },
    )
    return task
