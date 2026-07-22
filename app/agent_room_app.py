from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import governance_service
import phase14_app
import pilot_bootstrap  # noqa: F401 — install commercial and Pilot runtime
from agent_room_models import (
    AgentRoom,
    AgentRoomMessageCreate,
    AgentRoomNote,
    AgentRoomNoteCreate,
    AgentRoomTaskCreate,
    AgentRoomUpdate,
    note_view,
    room_view,
)
from agent_room_service import (
    ACTIVE_TASK_STATUSES,
    agent_for_tenant,
    aware,
    ensure_room,
    ensure_room_mission,
    room_detail_view,
    room_key_for,
    room_summary,
    safe_asset_path,
    seed_agent_rooms,
)
from collaboration_models import CollaborationTask, task_view
from collaboration_service import collaboration_event, create_message, dispatch_task
from enterprise_service import scope_resource
from governance_models import GovernanceRole
from main import (
    MissionEvent,
    RuntimeConnector,
    SessionLocal,
    app,
    bounded_payload,
    db_session,
    utcnow,
)
from phase6_app import require_governance
from phase12_app import tenant_header
from registry_models import RegisteredAgent
from release_version import APP_VERSION

app.version = APP_VERSION

_AGENT_ROOM_RULES = [
    ("PATCH", re.compile(r"^/api/agent-rooms/[^/]+$"), "agent-room:write"),
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/messages$"), "agent-room:message"),
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/tasks$"), "agent-room:assign"),
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/notes$"), "agent-room:write"),
    ("DELETE", re.compile(r"^/api/agent-rooms/[^/]+/notes/[^/]+$"), "agent-room:write"),
]
for rule in reversed(_AGENT_ROOM_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.update(
    {"agent-room:write", "agent-room:message", "agent-room:assign"}
)

phase14_app._FEATURE_ROUTES.insert(
    0,
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/(messages|tasks)$"), "collaboration"),
)
phase14_app._FEATURE_ROUTES.insert(
    0,
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/notes$"), "registry"),
)


def ensure_room_permissions(db: Session) -> None:
    additions = {
        "role:executive": {
            "agent-room:read",
            "agent-room:write",
            "agent-room:message",
            "agent-room:assign",
        },
        "role:manager": {
            "agent-room:read",
            "agent-room:write",
            "agent-room:message",
            "agent-room:assign",
        },
        "role:operator": {
            "agent-room:read",
            "agent-room:message",
            "agent-room:assign",
        },
        "role:auditor": {"agent-room:read"},
        "role:service": {
            "agent-room:read",
            "agent-room:message",
            "agent-room:assign",
        },
        "role:agent": {"agent-room:read", "agent-room:message"},
        "role:runtime": {"agent-room:read"},
    }
    changed = False
    for role_key, permissions in additions.items():
        role = db.scalar(select(GovernanceRole).where(GovernanceRole.role_key == role_key))
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
def start_agent_rooms() -> None:
    with SessionLocal() as db:
        ensure_room_permissions(db)
        seed_agent_rooms(db, "tenant:beeza")


def get_room_agent(
    db: Session,
    tenant_key: str,
    agent_key: str,
    actor: str = "system:agent-rooms",
) -> tuple[AgentRoom, RegisteredAgent]:
    agent = agent_for_tenant(db, tenant_key, agent_key)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent Room not found")
    room = ensure_room(db, tenant_key, agent, actor)
    db.commit()
    db.refresh(room)
    return room, agent


@app.get("/api/agent-rooms/status")
def agent_room_status(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("agent-room:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    seed_agent_rooms(db, tenant_key)
    rooms = list(
        db.scalars(
            select(AgentRoom).where(AgentRoom.tenant_key == tenant_key)
        ).all()
    )
    agents = [
        agent_for_tenant(db, tenant_key, room.agent_key)
        for room in rooms
    ]
    valid_agents = [agent for agent in agents if agent is not None]
    return {
        "version": APP_VERSION,
        "tenant_key": tenant_key,
        "rooms": len(rooms),
        "open": sum(room.room_status == "OPEN" for room in rooms),
        "focus": sum(room.room_status == "FOCUS" for room in rooms),
        "busy_agents": sum(agent.availability == "BUSY" for agent in valid_agents),
        "waiting_agents": sum(agent.availability == "WAITING" for agent in valid_agents),
        "placeholder_assets": sum(
            room.background_asset.endswith("agent-room-placeholder.svg") for room in rooms
        ),
    }


@app.get("/api/agent-rooms")
def list_agent_rooms(
    department_key: str | None = Query(default=None, max_length=100),
    availability: str | None = Query(default=None, max_length=30),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("agent-room:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    seed_agent_rooms(db, tenant_key)
    rooms = list(
        db.scalars(
            select(AgentRoom)
            .where(AgentRoom.tenant_key == tenant_key)
            .order_by(AgentRoom.title)
        ).all()
    )
    output: list[dict[str, Any]] = []
    for room in rooms:
        agent = agent_for_tenant(db, tenant_key, room.agent_key)
        if agent is None:
            continue
        if department_key and agent.department_key != department_key:
            continue
        if availability and agent.availability != availability.upper():
            continue
        output.append(room_summary(db, room, agent))
    return output


@app.get("/api/agent-rooms/{agent_key}")
def read_agent_room(
    agent_key: str,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    return room_detail_view(db, room, agent)


@app.patch("/api/agent-rooms/{agent_key}")
def update_agent_room(
    agent_key: str,
    payload: AgentRoomUpdate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    changes = payload.model_dump(exclude_unset=True)
    for field in {"background_asset", "avatar_asset", "foreground_asset"}:
        if field in changes and changes[field] is not None:
            try:
                changes[field] = safe_asset_path(changes[field])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "layout" in changes and changes["layout"] is not None:
        changes["layout"] = bounded_payload(changes["layout"])
    if "pinned_items" in changes and changes["pinned_items"] is not None:
        changes["pinned_items"] = bounded_payload(changes["pinned_items"])
    for field, value in changes.items():
        setattr(room, field, value)
    room.updated_at = utcnow()
    db.commit()
    db.refresh(room)
    return room_detail_view(db, room, agent)


@app.post("/api/agent-rooms/{agent_key}/messages", status_code=201)
def send_agent_room_message(
    agent_key: str,
    payload: AgentRoomMessageCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:message")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    mission = ensure_room_mission(db, tenant_key, room, agent, actor)
    message = create_message(
        db,
        mission_key=mission.mission_key,
        task_key=None,
        message_type=payload.message_type,
        source_identity=actor,
        target_identity=agent.identity_key,
        subject=payload.subject,
        body=payload.body,
        payload={
            "agent_room_key": room.room_key,
            "agent_key": agent.agent_key,
            "channel": "DIRECT_ROOM",
        },
        status="DELIVERED",
        reply_required=payload.reply_required,
    )
    scope_resource(
        db,
        "collaboration_message",
        message.message_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    db.add(
        MissionEvent(
            mission_key=mission.mission_key,
            actor=actor[:80],
            event_type="ROOM_MESSAGE",
            message=f"Direct message to {agent.display_name}: {payload.subject}"[:800],
            created_at=utcnow(),
        )
    )
    db.commit()
    db.refresh(message)
    return room_detail_view(db, room, agent)


@app.post("/api/agent-rooms/{agent_key}/tasks", status_code=201)
async def assign_agent_room_task(
    agent_key: str,
    payload: AgentRoomTaskCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:assign")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    if agent.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Agent is not active")
    runtime = db.scalar(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key == agent.preferred_runtime_key
        )
    )
    if runtime is None:
        raise HTTPException(status_code=409, detail="Agent runtime is not registered")
    mission = ensure_room_mission(db, tenant_key, room, agent, actor)
    now = utcnow()
    task = CollaborationTask(
        task_key=f"TASK-{uuid4().hex[:12].upper()}",
        mission_key=mission.mission_key,
        parent_task_key=None,
        title=payload.title,
        objective=payload.objective,
        source_identity=actor,
        target_identity=agent.identity_key,
        target_runtime_key=agent.preferred_runtime_key,
        status="QUEUED",
        priority=payload.priority,
        review_policy=payload.review_policy,
        auto_dispatch=payload.auto_dispatch,
        depends_on=[],
        inputs=[],
        expected_outputs=payload.expected_outputs,
        acceptance_criteria=payload.acceptance_criteria,
        context=bounded_payload(
            {
                **payload.context,
                "agent_room_key": room.room_key,
                "agent_key": agent.agent_key,
                "assignment_source": "AGENT_ROOM",
            }
        ),
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
    message = create_message(
        db,
        mission_key=mission.mission_key,
        task_key=task.task_key,
        message_type="ASSIGN",
        source_identity=actor,
        target_identity=agent.identity_key,
        subject=task.title,
        body=task.objective,
        payload={
            "priority": task.priority,
            "expected_outputs": task.expected_outputs,
            "acceptance_criteria": task.acceptance_criteria,
            "agent_room_key": room.room_key,
        },
        status="DELIVERED",
        reply_required=True,
        due_at=task.deadline_at,
    )
    scope_resource(
        db,
        "collaboration_task",
        task.task_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    scope_resource(
        db,
        "collaboration_message",
        message.message_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    collaboration_event(
        db,
        task,
        "ROOM_TASK_ASSIGNED",
        actor,
        f"Assigned from {room.title} to {agent.display_name}.",
        {"agent_room_key": room.room_key},
    )
    db.add(
        MissionEvent(
            mission_key=mission.mission_key,
            actor=actor[:80],
            event_type="ROOM_TASK_ASSIGNED",
            message=f"{task.task_key} → {agent.display_name}: {task.title}"[:800],
            created_at=now,
        )
    )
    mission.status = "EXECUTING"
    mission.waiting_for = f"{agent.display_name} assigned {task.task_key}"
    room.room_status = "FOCUS"
    room.status_message = f"Working on {task.title}"
    room.updated_at = now
    db.commit()
    db.refresh(task)
    if task.auto_dispatch:
        await dispatch_task(db, task)
        db.refresh(task)
    return {
        "task": task_view(task),
        "room": room_detail_view(db, room, agent),
    }


@app.post("/api/agent-rooms/{agent_key}/notes", status_code=201)
def create_agent_room_note(
    agent_key: str,
    payload: AgentRoomNoteCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    now = utcnow()
    note = AgentRoomNote(
        note_key=f"NOTE-{uuid4().hex[:14].upper()}",
        tenant_key=tenant_key,
        room_key=room.room_key,
        note_kind=payload.note_kind,
        title=payload.title,
        body=payload.body,
        pinned=payload.pinned,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    db.flush()
    scope_resource(
        db,
        "agent_room_note",
        note.note_key,
        tenant_key,
        classification=agent.data_clearance,
        created_by=actor,
    )
    db.commit()
    db.refresh(note)
    return {
        "note": note_view(note),
        "room": room_detail_view(db, room, agent),
    }


@app.delete("/api/agent-rooms/{agent_key}/notes/{note_key}")
def delete_agent_room_note(
    agent_key: str,
    note_key: str,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("agent-room:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    room, agent = get_room_agent(db, tenant_key, agent_key, actor)
    note = db.scalar(
        select(AgentRoomNote).where(
            AgentRoomNote.note_key == note_key,
            AgentRoomNote.tenant_key == tenant_key,
            AgentRoomNote.room_key == room.room_key,
        )
    )
    if note is None:
        raise HTTPException(status_code=404, detail="Agent Room note not found")
    db.delete(note)
    db.commit()
    return room_detail_view(db, room, agent)
