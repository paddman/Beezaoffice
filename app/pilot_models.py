from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

PILOT_STATUSES = {
    "DRAFT",
    "READY",
    "RUNNING",
    "BLOCKED",
    "AWAITING_ACCEPTANCE",
    "ACCEPTED",
    "REJECTED",
    "CANCELLED",
}
GATE_STATUSES = {"PENDING", "RUNNING", "PASS", "FAIL", "BLOCKED", "SKIPPED"}
DECISIONS = {"ACCEPT", "REJECT", "PAUSE", "REOPEN"}

PILOT_GATES = [
    "release_signed",
    "license_lifecycle",
    "schema_migration",
    "tenant_isolation",
    "runtime_e2e",
    "backup_restore",
    "load_test",
    "security_review",
    "upgrade_rollback",
    "customer_acceptance",
]


class PilotProgram(Base):
    __tablename__ = "pilot_programs"
    __table_args__ = (
        UniqueConstraint("tenant_key", "target_version", name="uq_pilot_tenant_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pilot_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    customer_name: Mapped[str] = mapped_column(String(240))
    environment: Mapped[str] = mapped_column(String(40), default="pilot")
    target_version: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    owner_identity: Mapped[str] = mapped_column(String(180))
    runtime_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    acceptance_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    accepted_by: Mapped[str | None] = mapped_column(String(180), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PilotGateEvidence(Base):
    __tablename__ = "pilot_gate_evidence"
    __table_args__ = (
        UniqueConstraint("pilot_key", "gate_key", name="uq_pilot_gate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    pilot_key: Mapped[str] = mapped_column(String(100), index=True)
    gate_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    source: Mapped[str] = mapped_column(String(80), default="MANUAL")
    summary: Mapped[str] = mapped_column(String(3000), default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_ref: Mapped[str] = mapped_column(String(1000), default="")
    integrity_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    recorded_by: Mapped[str] = mapped_column(String(180))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PilotProgramCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=240)
    environment: str = Field(default="pilot", pattern="^(pilot|staging|production)$")
    target_version: str = Field(default="0.16.0", min_length=3, max_length=40)
    runtime_keys: list[str] = Field(default_factory=list, max_length=20)
    acceptance_criteria: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=10000)


class PilotGateUpsert(BaseModel):
    gate_key: str = Field(min_length=3, max_length=100)
    status: str = Field(pattern="^(PENDING|RUNNING|PASS|FAIL|BLOCKED|SKIPPED)$")
    source: str = Field(default="MANUAL", min_length=2, max_length=80)
    summary: str = Field(default="", max_length=3000)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str = Field(default="", max_length=1000)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PilotDecision(BaseModel):
    decision: str = Field(pattern="^(ACCEPT|REJECT|PAUSE|REOPEN)$")
    note: str = Field(default="", max_length=5000)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def pilot_view(row: PilotProgram) -> dict[str, Any]:
    return {
        "key": row.pilot_key,
        "tenant_key": row.tenant_key,
        "customer_name": row.customer_name,
        "environment": row.environment,
        "target_version": row.target_version,
        "status": row.status,
        "owner_identity": row.owner_identity,
        "runtime_keys": row.runtime_keys,
        "acceptance_criteria": row.acceptance_criteria,
        "notes": row.notes,
        "accepted_by": row.accepted_by,
        "accepted_at": iso(row.accepted_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def gate_view(row: PilotGateEvidence) -> dict[str, Any]:
    return {
        "key": row.evidence_key,
        "pilot_key": row.pilot_key,
        "gate_key": row.gate_key,
        "status": row.status,
        "source": row.source,
        "summary": row.summary,
        "metrics": row.metrics,
        "artifact_ref": row.artifact_ref,
        "integrity_hash": row.integrity_hash,
        "recorded_by": row.recorded_by,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "updated_at": iso(row.updated_at),
    }
