from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

PROTOCOL_TASK_STATES = {
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}
TERMINAL_PROTOCOL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}


class ProtocolTask(Base):
    __tablename__ = "protocol_tasks"
    __table_args__ = (
        UniqueConstraint("protocol", "client_identity", "message_id", name="uq_protocol_client_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    protocol: Mapped[str] = mapped_column(String(40), index=True)
    client_identity: Mapped[str] = mapped_column(String(180), index=True)
    message_id: Mapped[str] = mapped_column(String(180), index=True)
    context_id: Mapped[str] = mapped_column(String(180), index=True)
    state: Mapped[str] = mapped_column(String(50), default="TASK_STATE_SUBMITTED", index=True)
    mission_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    collaboration_task_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sop_run_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status_message: Mapped[str] = mapped_column(String(2000), default="Submitted")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProtocolEvent(Base):
    __tablename__ = "protocol_events"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_protocol_task_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(120), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookReceipt(Base):
    __tablename__ = "protocol_webhook_receipts"
    __table_args__ = (
        UniqueConstraint("channel_key", "idempotency_key", name="uq_protocol_webhook_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    channel_key: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), index=True)
    client_identity: Mapped[str] = mapped_column(String(180), index=True)
    mode: Mapped[str] = mapped_column(String(30), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    protocol_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    sop_run_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="ACCEPTED", index=True)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class A2APart(BaseModel):
    text: str | None = Field(default=None, max_length=20000)
    data: dict[str, Any] | None = None


class A2AMessage(BaseModel):
    messageId: str | None = Field(default=None, max_length=180)
    role: str = Field(default="ROLE_USER", pattern="^(ROLE_USER|ROLE_AGENT|user|agent)$")
    parts: list[A2APart] = Field(min_length=1, max_length=50)
    contextId: str | None = Field(default=None, max_length=180)
    taskId: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ASendConfiguration(BaseModel):
    acceptedOutputModes: list[str] = Field(default_factory=lambda: ["text/plain"], max_length=20)
    returnImmediately: bool = False


class A2ASendRequest(BaseModel):
    message: A2AMessage
    configuration: A2ASendConfiguration = Field(default_factory=A2ASendConfiguration)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant", "developer", "tool"]
    content: str | list[dict[str, Any]]


class OpenAIChatRequest(BaseModel):
    model: str = Field(default="beeza/auto", min_length=1, max_length=180)
    messages: list[OpenAIMessage] = Field(min_length=1, max_length=100)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=1000000)
    user: str | None = Field(default=None, max_length=180)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookIngress(BaseModel):
    mode: Literal["task", "sop"] = "task"
    idempotency_key: str | None = Field(default=None, max_length=180)
    title: str | None = Field(default=None, max_length=240)
    objective: str | None = Field(default=None, max_length=3000)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=100)
    required_tools: list[str] = Field(default_factory=list, max_length=100)
    required_clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    preferred_runtime_key: str | None = Field(default=None, max_length=80)
    template_key: str | None = Field(default=None, max_length=100)
    inputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def protocol_task_view(row: ProtocolTask) -> dict[str, Any]:
    return {
        "id": row.task_id,
        "protocol": row.protocol,
        "client_identity": row.client_identity,
        "message_id": row.message_id,
        "context_id": row.context_id,
        "state": row.state,
        "mission_key": row.mission_key,
        "collaboration_task_key": row.collaboration_task_key,
        "sop_run_key": row.sop_run_key,
        "status_message": row.status_message,
        "artifacts": row.artifacts,
        "error": row.error,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "completed_at": iso(row.completed_at),
    }


def webhook_receipt_view(row: WebhookReceipt) -> dict[str, Any]:
    return {
        "key": row.receipt_key,
        "channel_key": row.channel_key,
        "idempotency_key": row.idempotency_key,
        "client_identity": row.client_identity,
        "mode": row.mode,
        "payload_hash": row.payload_hash,
        "protocol_task_id": row.protocol_task_id,
        "sop_run_key": row.sop_run_key,
        "status": row.status,
        "response": row.response_payload,
        "received_at": iso(row.received_at),
    }
