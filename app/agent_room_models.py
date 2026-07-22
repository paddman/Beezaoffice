from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

ROOM_STATUSES = {"OPEN", "FOCUS", "AWAY", "MAINTENANCE"}
VISITOR_POLICIES = {"PRIVATE", "DEPARTMENT", "TENANT"}
NOTE_KINDS = {"NOTE", "MEMORY", "REMINDER"}


class AgentRoom(Base):
    __tablename__ = "agent_rooms"
    __table_args__ = (
        UniqueConstraint("tenant_key", "agent_key", name="uq_agent_room_tenant_agent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    agent_key: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    room_status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    status_message: Mapped[str] = mapped_column(String(500), default="Ready for work")
    theme_key: Mapped[str] = mapped_column(String(80), default="electric-office")
    background_asset: Mapped[str] = mapped_column(
        String(500), default="/static/assets/agent-room-placeholder.svg"
    )
    avatar_asset: Mapped[str] = mapped_column(
        String(500), default="/static/assets/agent-avatar-placeholder.svg"
    )
    foreground_asset: Mapped[str] = mapped_column(String(500), default="")
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pinned_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    visitor_policy: Mapped[str] = mapped_column(String(30), default="TENANT")
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AgentRoomNote(Base):
    __tablename__ = "agent_room_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    room_key: Mapped[str] = mapped_column(String(100), index=True)
    note_kind: Mapped[str] = mapped_column(String(30), default="NOTE", index=True)
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(String(180), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AgentRoomUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    room_status: str | None = Field(
        default=None, pattern="^(OPEN|FOCUS|AWAY|MAINTENANCE)$"
    )
    status_message: str | None = Field(default=None, max_length=500)
    theme_key: str | None = Field(default=None, min_length=2, max_length=80)
    background_asset: str | None = Field(default=None, max_length=500)
    avatar_asset: str | None = Field(default=None, max_length=500)
    foreground_asset: str | None = Field(default=None, max_length=500)
    layout: dict[str, Any] | None = None
    pinned_items: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    visitor_policy: str | None = Field(
        default=None, pattern="^(PRIVATE|DEPARTMENT|TENANT)$"
    )


class AgentRoomMessageCreate(BaseModel):
    subject: str = Field(default="Direct message", min_length=3, max_length=240)
    body: str = Field(min_length=1, max_length=3000)
    message_type: str = Field(default="REQUEST_INFO", pattern="^(REQUEST_INFO|FYI)$")
    reply_required: bool = True


class AgentRoomTaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    review_policy: str = Field(default="AUTO", pattern="^(AUTO|HUMAN)$")
    auto_dispatch: bool = True
    expected_outputs: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)
    deadline_at: datetime | None = None


class AgentRoomNoteCreate(BaseModel):
    note_kind: str = Field(default="NOTE", pattern="^(NOTE|MEMORY|REMINDER)$")
    title: str = Field(min_length=2, max_length=240)
    body: str = Field(default="", max_length=10000)
    pinned: bool = False


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def room_view(row: AgentRoom) -> dict[str, Any]:
    return {
        "key": row.room_key,
        "tenant_key": row.tenant_key,
        "agent_key": row.agent_key,
        "title": row.title,
        "subtitle": row.subtitle,
        "room_status": row.room_status,
        "status_message": row.status_message,
        "theme_key": row.theme_key,
        "background_asset": row.background_asset,
        "avatar_asset": row.avatar_asset,
        "foreground_asset": row.foreground_asset,
        "layout": row.layout,
        "pinned_items": row.pinned_items,
        "visitor_policy": row.visitor_policy,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def note_view(row: AgentRoomNote) -> dict[str, Any]:
    return {
        "key": row.note_key,
        "tenant_key": row.tenant_key,
        "room_key": row.room_key,
        "kind": row.note_kind,
        "title": row.title,
        "body": row.body,
        "pinned": row.pinned,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
