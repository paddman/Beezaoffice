from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

TASK_STATUSES = {
    "DRAFT", "WAITING_DEPENDENCY", "QUEUED", "DISPATCHING", "RUNNING",
    "WAITING_APPROVAL", "REVIEW", "REVISION", "COMPLETED", "BLOCKED",
    "FAILED", "CANCELLED", "ESCALATED",
}
TERMINAL_TASK_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
MESSAGE_TYPES = {
    "ASSIGN", "ACCEPT", "REJECT", "REQUEST_INFO", "RESPONSE", "HANDOFF",
    "REVIEW", "REVISION", "BLOCKED", "FOLLOW_UP", "DECISION", "FYI",
    "ESCALATION", "COMPLETION",
}
MESSAGE_STATUSES = {
    "CREATED", "DELIVERED", "SEEN", "ACCEPTED", "IN_PROGRESS",
    "RESPONDED", "EXPIRED", "ESCALATED",
}


class CollaborationTask(Base):
    __tablename__ = "collaboration_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    parent_task_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(String(3000))
    source_identity: Mapped[str] = mapped_column(String(160))
    target_identity: Mapped[str] = mapped_column(String(160))
    target_runtime_key: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    review_policy: Mapped[str] = mapped_column(String(20), default="AUTO")
    auto_dispatch: Mapped[bool] = mapped_column(Boolean, default=True)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    inputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    expected_outputs: Mapped[list[str]] = mapped_column(JSON, default=list)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dispatch_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)
    last_progress_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CollaborationMessage(Base):
    __tablename__ = "collaboration_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    task_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    message_type: Mapped[str] = mapped_column(String(40), index=True)
    source_identity: Mapped[str] = mapped_column(String(160), index=True)
    target_identity: Mapped[str] = mapped_column(String(160), index=True)
    subject: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(40), default="CREATED", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reply_required: Mapped[bool] = mapped_column(Boolean, default=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HandoffCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    source_identity: str = Field(default="agent:Beeza Commander", min_length=3, max_length=160)
    target_runtime_key: str = Field(min_length=2, max_length=80)
    target_identity: str | None = Field(default=None, max_length=160)
    parent_task_key: str | None = Field(default=None, max_length=100)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    review_policy: str = Field(default="AUTO", pattern="^(AUTO|HUMAN)$")
    auto_dispatch: bool = True
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    inputs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    expected_outputs: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)
    deadline_at: datetime | None = None


class CollaborationMessageCreate(BaseModel):
    task_key: str | None = Field(default=None, max_length=100)
    message_type: str = Field(pattern="^(ASSIGN|ACCEPT|REJECT|REQUEST_INFO|RESPONSE|HANDOFF|REVIEW|REVISION|BLOCKED|FOLLOW_UP|DECISION|FYI|ESCALATION|COMPLETION)$")
    source_identity: str = Field(min_length=3, max_length=160)
    target_identity: str = Field(min_length=3, max_length=160)
    subject: str = Field(min_length=3, max_length=240)
    body: str = Field(min_length=1, max_length=3000)
    payload: dict[str, Any] = Field(default_factory=dict)
    reply_required: bool = False
    due_at: datetime | None = None


class TaskAction(BaseModel):
    action: str = Field(pattern="^(accept|block|resume|complete|cancel|retry)$")
    note: str | None = Field(default=None, max_length=2000)
    result: dict[str, Any] = Field(default_factory=dict)


class TaskReview(BaseModel):
    decision: str = Field(pattern="^(accept|revise|reject)$")
    note: str | None = Field(default=None, max_length=2000)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def task_view(row: CollaborationTask) -> dict[str, Any]:
    return {
        "key": row.task_key, "mission_key": row.mission_key,
        "parent_task_key": row.parent_task_key, "title": row.title,
        "objective": row.objective, "source_identity": row.source_identity,
        "target_identity": row.target_identity, "target_runtime_key": row.target_runtime_key,
        "status": row.status, "priority": row.priority,
        "review_policy": row.review_policy, "auto_dispatch": row.auto_dispatch,
        "depends_on": row.depends_on, "inputs": row.inputs,
        "expected_outputs": row.expected_outputs,
        "acceptance_criteria": row.acceptance_criteria, "context": row.context,
        "result": row.result, "dispatch_key": row.dispatch_key,
        "attempts": row.attempts, "follow_up_count": row.follow_up_count,
        "last_progress_at": iso(row.last_progress_at),
        "next_follow_up_at": iso(row.next_follow_up_at),
        "deadline_at": iso(row.deadline_at), "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def message_view(row: CollaborationMessage) -> dict[str, Any]:
    return {
        "key": row.message_key, "mission_key": row.mission_key,
        "task_key": row.task_key, "type": row.message_type,
        "source_identity": row.source_identity, "target_identity": row.target_identity,
        "subject": row.subject, "body": row.body, "status": row.status,
        "payload": row.payload, "reply_required": row.reply_required,
        "due_at": iso(row.due_at), "created_at": iso(row.created_at),
        "delivered_at": iso(row.delivered_at),
        "acknowledged_at": iso(row.acknowledged_at),
        "responded_at": iso(row.responded_at),
    }
