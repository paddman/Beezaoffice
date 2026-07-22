from __future__ import annotations

from sqlalchemy.orm import Session

import agent_room_app
import agent_room_service
from agent_room_models import AgentRoom
from main import utcnow
from registry_models import RegisteredAgent

_original_room_summary = agent_room_service.room_summary
_original_room_detail_view = agent_room_service.room_detail_view


def reconcile_room_presence(
    db: Session,
    room: AgentRoom,
    agent: RegisteredAgent,
) -> None:
    if room.room_status in {"AWAY", "MAINTENANCE"}:
        return
    tasks = agent_room_service.room_tasks(db, agent, 100)
    active = next(
        (
            task
            for task in tasks
            if task.status in agent_room_service.ACTIVE_TASK_STATUSES
        ),
        None,
    )
    desired_status = "FOCUS" if active or agent.availability == "BUSY" else "OPEN"
    desired_message = (
        f"Working on {active.title}"
        if active is not None
        else "Waiting for required input"
        if agent.availability == "WAITING"
        else "Ready for work"
    )
    if room.room_status != desired_status or room.status_message != desired_message:
        room.room_status = desired_status
        room.status_message = desired_message
        room.updated_at = utcnow()
        db.commit()
        db.refresh(room)


def presence_room_summary(
    db: Session,
    room: AgentRoom,
    agent: RegisteredAgent,
):
    reconcile_room_presence(db, room, agent)
    return _original_room_summary(db, room, agent)


def presence_room_detail_view(
    db: Session,
    room: AgentRoom,
    agent: RegisteredAgent,
):
    reconcile_room_presence(db, room, agent)
    return _original_room_detail_view(db, room, agent)


agent_room_service.room_summary = presence_room_summary
agent_room_service.room_detail_view = presence_room_detail_view
agent_room_app.room_summary = presence_room_summary
agent_room_app.room_detail_view = presence_room_detail_view
