from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

MEETING_STATUSES = {
    "DRAFT", "SCHEDULED", "RUNNING", "AWAITING_DECISION",
    "COMPLETED", "CANCELLED", "FAILED",
}
TURN_STATUSES = {
    "QUEUED", "DISPATCHING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED",
}
PARTICIPANT_ROLES = {
    "MODERATOR", "EXECUTIVE", "DOMAIN", "CRITIC", "PMO", "OBSERVER",
}
DECISION_STATUSES = {"ACCEPTED", "REJECTED", "OVERRIDDEN"}
DECISION_RULES = {"CONSENSUS", "MAJORITY", "EXECUTIVE"}


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(String(3000))
    agenda: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=2)
    decision_rule: Mapped[str] = mapped_column(String(30), default="EXECUTIVE")
    moderator_identity: Mapped[str] = mapped_column(String(160))
    owner_identity: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(String(6000), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    meeting_key: Mapped[str] = mapped_column(String(100), index=True)
    identity: Mapped[str] = mapped_column(String(160))
    runtime_key: Mapped[str] = mapped_column(String(80), index=True)
    role: Mapped[str] = mapped_column(String(30))
    speaking_order: Mapped[int] = mapped_column(Integer)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    instructions: Mapped[str] = mapped_column(String(2000), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MeetingTurn(Base):
    __tablename__ = "meeting_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    meeting_key: Mapped[str] = mapped_column(String(100), index=True)
    participant_key: Mapped[str] = mapped_column(String(100), index=True)
    round_number: Mapped[int] = mapped_column(Integer, index=True)
    speaking_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    prompt: Mapped[str] = mapped_column(String(8000), default="")
    dispatch_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    contribution: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MeetingDecision(Base):
    __tablename__ = "meeting_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    meeting_key: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(240))
    rationale: Mapped[str] = mapped_column(String(5000))
    status: Mapped[str] = mapped_column(String(30))
    decided_by: Mapped[str] = mapped_column(String(160))
    confidence: Mapped[float] = mapped_column(Float)
    votes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    generated_task_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MeetingParticipantCreate(BaseModel):
    identity: str = Field(min_length=3, max_length=160)
    runtime_key: str = Field(min_length=2, max_length=80)
    role: str = Field(pattern="^(MODERATOR|EXECUTIVE|DOMAIN|CRITIC|PMO|OBSERVER)$")
    instructions: str = Field(default="", max_length=2000)
    required: bool = True


class MeetingCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    agenda: list[str] = Field(default_factory=list, max_length=30)
    max_rounds: int = Field(default=2, ge=1, le=5)
    decision_rule: str = Field(default="EXECUTIVE", pattern="^(CONSENSUS|MAJORITY|EXECUTIVE)$")
    moderator_identity: str = Field(default="agent:Beeza Moderator", min_length=3, max_length=160)
    owner_identity: str = Field(default="agent:Beeza Commander", min_length=3, max_length=160)
    participants: list[MeetingParticipantCreate] = Field(min_length=2, max_length=12)


class MeetingActionItemCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    target_runtime_key: str = Field(min_length=2, max_length=80)
    target_identity: str | None = Field(default=None, max_length=160)
    owner_identity: str | None = Field(default=None, max_length=160)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    review_policy: str = Field(default="AUTO", pattern="^(AUTO|HUMAN)$")
    expected_outputs: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    deadline_at: datetime | None = None


class MeetingDecisionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    rationale: str = Field(min_length=5, max_length=5000)
    status: str = Field(default="ACCEPTED", pattern="^(ACCEPTED|REJECTED|OVERRIDDEN)$")
    decided_by: str = Field(min_length=3, max_length=160)
    confidence: float = Field(ge=0.0, le=1.0)
    votes: dict[str, Any] = Field(default_factory=dict)
    action_items: list[MeetingActionItemCreate] = Field(default_factory=list, max_length=50)


class MeetingAction(BaseModel):
    action: str = Field(pattern="^(start|tick|cancel)$")
    note: str | None = Field(default=None, max_length=2000)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def participant_view(row: MeetingParticipant) -> dict[str, Any]:
    return {
        "key": row.participant_key,
        "meeting_key": row.meeting_key,
        "identity": row.identity,
        "runtime_key": row.runtime_key,
        "role": row.role,
        "speaking_order": row.speaking_order,
        "required": row.required,
        "instructions": row.instructions,
        "active": row.active,
        "created_at": iso(row.created_at),
    }


def turn_view(row: MeetingTurn) -> dict[str, Any]:
    return {
        "key": row.turn_key,
        "meeting_key": row.meeting_key,
        "participant_key": row.participant_key,
        "round_number": row.round_number,
        "speaking_order": row.speaking_order,
        "status": row.status,
        "prompt": row.prompt,
        "dispatch_key": row.dispatch_key,
        "contribution": row.contribution,
        "confidence": row.confidence,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def decision_view(row: MeetingDecision) -> dict[str, Any]:
    return {
        "key": row.decision_key,
        "meeting_key": row.meeting_key,
        "title": row.title,
        "rationale": row.rationale,
        "status": row.status,
        "decided_by": row.decided_by,
        "confidence": row.confidence,
        "votes": row.votes,
        "action_items": row.action_items,
        "generated_task_keys": row.generated_task_keys,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def meeting_view(row: Meeting) -> dict[str, Any]:
    return {
        "key": row.meeting_key,
        "mission_key": row.mission_key,
        "title": row.title,
        "objective": row.objective,
        "agenda": row.agenda,
        "status": row.status,
        "current_round": row.current_round,
        "max_rounds": row.max_rounds,
        "decision_rule": row.decision_rule,
        "moderator_identity": row.moderator_identity,
        "owner_identity": row.owner_identity,
        "summary": row.summary,
        "started_at": iso(row.started_at),
        "ended_at": iso(row.ended_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
