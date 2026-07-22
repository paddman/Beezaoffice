from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent_room_models import AgentRoom, AgentRoomNote, note_view, room_view
from collaboration_models import (
    CollaborationMessage,
    CollaborationTask,
    message_view,
    task_view,
)
from enterprise_service import scope_resource
from evaluation_models import EvaluationRun, evaluation_view
from governance_models import GovernanceIdentity
from main import Mission, MissionEvent, RuntimeDispatch, utcnow
from meeting_models import Meeting, MeetingParticipant, meeting_view
from registry_models import RegisteredAgent
from registry_service import agent_detail

ACTIVE_TASK_STATUSES = {
    "WAITING_DEPENDENCY",
    "QUEUED",
    "DISPATCHING",
    "RUNNING",
    "WAITING_APPROVAL",
    "REVIEW",
    "REVISION",
    "BLOCKED",
    "ESCALATED",
}

THEME_BY_DEPARTMENT = {
    "dept:executive": "executive-sky",
    "dept:operations": "operations-electric",
    "dept:data": "data-lab",
    "dept:quality": "quality-white",
    "dept:finance": "finance-indigo",
    "dept:support": "support-coral",
    "dept:people": "people-warm",
    "dept:legal": "legal-navy",
    "dept:procurement": "procurement-slate",
    "dept:marketing": "marketing-cherry",
}


def compact_key(value: str, length: int = 14) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length].upper()


def room_key_for(tenant_key: str, agent_key: str) -> str:
    return f"ROOM-{compact_key(f'{tenant_key}:{agent_key}') }"


def room_mission_key_for(tenant_key: str, agent_key: str) -> str:
    return f"RM-{compact_key(f'{tenant_key}:{agent_key}:mission', 20)}"


def identity_aliases(agent: RegisteredAgent) -> list[str]:
    return list(
        dict.fromkeys(
            [
                agent.identity_key,
                f"agent:{agent.agent_key}",
                f"agent:{agent.display_name}",
                agent.agent_key,
                agent.display_name,
            ]
        )
    )


def agent_for_tenant(
    db: Session,
    tenant_key: str,
    agent_key: str,
) -> RegisteredAgent | None:
    statement = (
        select(RegisteredAgent)
        .join(
            GovernanceIdentity,
            GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
        )
        .where(
            RegisteredAgent.agent_key == agent_key,
            GovernanceIdentity.tenant_key == tenant_key,
        )
    )
    row = db.scalar(statement)
    if row is None and tenant_key == "tenant:beeza":
        row = db.scalar(
            select(RegisteredAgent).where(RegisteredAgent.agent_key == agent_key)
        )
    return row


def agents_for_tenant(db: Session, tenant_key: str) -> list[RegisteredAgent]:
    rows = list(
        db.scalars(
            select(RegisteredAgent)
            .join(
                GovernanceIdentity,
                GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
            )
            .where(GovernanceIdentity.tenant_key == tenant_key)
            .order_by(RegisteredAgent.department_key, RegisteredAgent.display_name)
        ).all()
    )
    if not rows and tenant_key == "tenant:beeza":
        rows = list(
            db.scalars(
                select(RegisteredAgent).order_by(
                    RegisteredAgent.department_key,
                    RegisteredAgent.display_name,
                )
            ).all()
        )
    return rows


def default_layout(agent: RegisteredAgent) -> dict[str, Any]:
    return {
        "scene": "office",
        "avatar_position": {"x": 50, "y": 76, "scale": 1.0},
        "hotspots": [
            {"key": "desk", "label": "Current work", "x": 22, "y": 72},
            {"key": "inbox", "label": "Inbox", "x": 76, "y": 28},
            {"key": "memory", "label": "Notes & memory", "x": 82, "y": 70},
        ],
        "asset_targets": {
            "background": f"/static/assets/agent-rooms/{agent.agent_key}/background.webp",
            "avatar": f"/static/assets/agent-rooms/{agent.agent_key}/avatar.webp",
            "foreground": f"/static/assets/agent-rooms/{agent.agent_key}/foreground.webp",
        },
    }


def ensure_room(
    db: Session,
    tenant_key: str,
    agent: RegisteredAgent,
    actor: str = "system:agent-rooms",
) -> AgentRoom:
    row = db.scalar(
        select(AgentRoom).where(
            AgentRoom.tenant_key == tenant_key,
            AgentRoom.agent_key == agent.agent_key,
        )
    )
    if row is not None:
        return row
    now = utcnow()
    row = AgentRoom(
        room_key=room_key_for(tenant_key, agent.agent_key),
        tenant_key=tenant_key,
        agent_key=agent.agent_key,
        title=f"{agent.display_name}'s Room",
        subtitle=f"{agent.role_title} · {agent.department_key.replace('dept:', '').title()}",
        room_status="OPEN",
        status_message="Ready for work",
        theme_key=THEME_BY_DEPARTMENT.get(agent.department_key, "electric-office"),
        background_asset="/static/assets/agent-room-placeholder.svg",
        avatar_asset="/static/assets/agent-avatar-placeholder.svg",
        foreground_asset="",
        layout=default_layout(agent),
        pinned_items=[],
        visitor_policy="TENANT",
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    scope_resource(
        db,
        "agent_room",
        row.room_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    return row


def seed_agent_rooms(db: Session, tenant_key: str, actor: str = "system:agent-rooms") -> int:
    created = 0
    for agent in agents_for_tenant(db, tenant_key):
        existing = db.scalar(
            select(AgentRoom.id).where(
                AgentRoom.tenant_key == tenant_key,
                AgentRoom.agent_key == agent.agent_key,
            )
        )
        if existing is None:
            ensure_room(db, tenant_key, agent, actor)
            created += 1
    db.commit()
    return created


def ensure_room_mission(
    db: Session,
    tenant_key: str,
    room: AgentRoom,
    agent: RegisteredAgent,
    actor: str,
) -> Mission:
    mission_key = room_mission_key_for(tenant_key, agent.agent_key)
    row = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if row is not None:
        scope_resource(
            db,
            "mission",
            row.mission_key,
            tenant_key,
            classification=agent.data_clearance,
            created_by=actor,
        )
        return row
    now = utcnow()
    row = Mission(
        mission_key=mission_key,
        title=f"Agent Room · {agent.display_name}",
        commander=agent.display_name,
        status="ACTIVE",
        priority="NORMAL",
        progress=0,
        waiting_for=None,
        objective=f"Persistent personal workspace for {agent.display_name}.",
        created_at=now,
    )
    db.add(row)
    db.flush()
    scope_resource(
        db,
        "mission",
        row.mission_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    db.add(
        MissionEvent(
            mission_key=row.mission_key,
            actor=actor[:80],
            event_type="AGENT_ROOM_OPENED",
            message=f"Persistent room mission created for {agent.display_name}."[:800],
            created_at=now,
        )
    )
    return row


def room_notes(db: Session, tenant_key: str, room_key: str) -> list[AgentRoomNote]:
    return list(
        db.scalars(
            select(AgentRoomNote)
            .where(
                AgentRoomNote.tenant_key == tenant_key,
                AgentRoomNote.room_key == room_key,
            )
            .order_by(AgentRoomNote.pinned.desc(), AgentRoomNote.updated_at.desc())
            .limit(100)
        ).all()
    )


def room_tasks(db: Session, agent: RegisteredAgent, limit: int = 100) -> list[CollaborationTask]:
    aliases = identity_aliases(agent)
    return list(
        db.scalars(
            select(CollaborationTask)
            .where(CollaborationTask.target_identity.in_(aliases))
            .order_by(CollaborationTask.updated_at.desc())
            .limit(limit)
        ).all()
    )


def room_messages(
    db: Session,
    agent: RegisteredAgent,
    limit: int = 100,
) -> list[CollaborationMessage]:
    aliases = identity_aliases(agent)
    return list(
        db.scalars(
            select(CollaborationMessage)
            .where(
                or_(
                    CollaborationMessage.target_identity.in_(aliases),
                    CollaborationMessage.source_identity.in_(aliases),
                )
            )
            .order_by(CollaborationMessage.created_at.desc())
            .limit(limit)
        ).all()
    )


def room_meetings(db: Session, agent: RegisteredAgent, limit: int = 50) -> list[Meeting]:
    aliases = identity_aliases(agent)
    meeting_keys = list(
        db.scalars(
            select(MeetingParticipant.meeting_key)
            .where(
                MeetingParticipant.identity.in_(aliases),
                MeetingParticipant.active.is_(True),
            )
            .limit(limit * 3)
        ).all()
    )
    if not meeting_keys:
        return []
    return list(
        db.scalars(
            select(Meeting)
            .where(Meeting.meeting_key.in_(meeting_keys))
            .order_by(Meeting.updated_at.desc())
            .limit(limit)
        ).all()
    )


def latest_evaluations_for_tasks(
    db: Session,
    tasks: list[CollaborationTask],
) -> list[EvaluationRun]:
    task_keys = [row.task_key for row in tasks]
    if not task_keys:
        return []
    rows = list(
        db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.task_key.in_(task_keys))
            .order_by(EvaluationRun.created_at.desc())
        ).all()
    )
    latest: dict[str, EvaluationRun] = {}
    for row in rows:
        latest.setdefault(row.task_key, row)
    return list(latest.values())


def room_activity(
    tasks: list[CollaborationTask],
    messages: list[CollaborationMessage],
    meetings: list[Meeting],
    notes: list[AgentRoomNote],
    limit: int = 80,
) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []
    for row in tasks:
        activity.append(
            {
                "type": "TASK",
                "key": row.task_key,
                "title": row.title,
                "detail": f"{row.status} · {row.priority}",
                "status": row.status,
                "at": row.updated_at.isoformat(),
            }
        )
    for row in messages:
        activity.append(
            {
                "type": "MESSAGE",
                "key": row.message_key,
                "title": row.subject,
                "detail": f"{row.source_identity} → {row.target_identity}",
                "status": row.status,
                "at": row.created_at.isoformat(),
            }
        )
    for row in meetings:
        activity.append(
            {
                "type": "MEETING",
                "key": row.meeting_key,
                "title": row.title,
                "detail": row.objective,
                "status": row.status,
                "at": row.updated_at.isoformat(),
            }
        )
    for row in notes:
        activity.append(
            {
                "type": row.note_kind,
                "key": row.note_key,
                "title": row.title,
                "detail": row.body[:300],
                "status": "PINNED" if row.pinned else "SAVED",
                "at": row.updated_at.isoformat(),
            }
        )
    activity.sort(key=lambda item: item["at"], reverse=True)
    return activity[:limit]


def room_summary(
    db: Session,
    room: AgentRoom,
    agent: RegisteredAgent,
) -> dict[str, Any]:
    tasks = room_tasks(db, agent, 300)
    messages = room_messages(db, agent, 300)
    meetings = room_meetings(db, agent, 100)
    notes = room_notes(db, room.tenant_key, room.room_key)
    evaluations = latest_evaluations_for_tasks(db, tasks)
    task_statuses = Counter(row.status for row in tasks)
    evaluation_statuses = Counter(row.status for row in evaluations)
    unread = sum(
        row.target_identity in identity_aliases(agent)
        and row.status in {"CREATED", "DELIVERED"}
        for row in messages
    )
    active_meetings = sum(row.status in {"SCHEDULED", "RUNNING", "AWAITING_DECISION"} for row in meetings)
    return {
        "room": room_view(room),
        "agent": agent_detail(db, agent),
        "counters": {
            "tasks_total": len(tasks),
            "tasks_active": sum(row.status in ACTIVE_TASK_STATUSES for row in tasks),
            "tasks_completed": task_statuses.get("COMPLETED", 0),
            "tasks_failed": task_statuses.get("FAILED", 0),
            "inbox_unread": unread,
            "messages_total": len(messages),
            "meetings_active": active_meetings,
            "notes": len(notes),
            "evaluation_pass": evaluation_statuses.get("PASS", 0),
            "evaluation_warn": evaluation_statuses.get("WARN", 0),
            "evaluation_fail": evaluation_statuses.get("FAIL", 0),
        },
    }


def room_detail_view(
    db: Session,
    room: AgentRoom,
    agent: RegisteredAgent,
) -> dict[str, Any]:
    tasks = room_tasks(db, agent)
    messages = room_messages(db, agent)
    meetings = room_meetings(db, agent)
    notes = room_notes(db, room.tenant_key, room.room_key)
    evaluations = latest_evaluations_for_tasks(db, tasks)
    dispatch_keys = [row.dispatch_key for row in tasks if row.dispatch_key]
    dispatches = []
    if dispatch_keys:
        dispatches = list(
            db.scalars(
                select(RuntimeDispatch)
                .where(RuntimeDispatch.dispatch_key.in_(dispatch_keys))
                .order_by(RuntimeDispatch.updated_at.desc())
            ).all()
        )
    summary = room_summary(db, room, agent)
    summary.update(
        {
            "tasks": [task_view(row) for row in tasks],
            "messages": [message_view(row) for row in messages],
            "meetings": [meeting_view(row) for row in meetings],
            "notes": [note_view(row) for row in notes],
            "evaluations": [evaluation_view(row) for row in evaluations],
            "dispatches": [
                {
                    "key": row.dispatch_key,
                    "runtime_key": row.runtime_key,
                    "mission_key": row.mission_key,
                    "remote_id": row.remote_id,
                    "status": row.status,
                    "output": row.output,
                    "error": row.error,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in dispatches
            ],
            "activity": room_activity(tasks, messages, meetings, notes),
            "asset_guide": {
                "background": f"app/static/assets/agent-rooms/{agent.agent_key}/background.webp",
                "avatar": f"app/static/assets/agent-rooms/{agent.agent_key}/avatar.webp",
                "foreground": f"app/static/assets/agent-rooms/{agent.agent_key}/foreground.webp",
                "recommended_background": "1920×1080 WebP",
                "recommended_avatar": "transparent WebP or PNG, 1024×1024",
                "recommended_foreground": "transparent WebP or PNG, 1920×1080",
            },
        }
    )
    return summary


def safe_asset_path(value: str) -> str:
    path = str(value or "").strip()
    if not path:
        return ""
    if not path.startswith("/static/"):
        raise ValueError("Agent Room assets must use a /static/ path")
    if any(token in path for token in {"..", "\\", "\x00"}):
        raise ValueError("Agent Room asset path is invalid")
    return path


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
