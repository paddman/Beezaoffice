from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

TEMPLATE_STATUSES = {"DRAFT", "PUBLISHED", "DEPRECATED"}
VERSION_STATUSES = {"DRAFT", "PUBLISHED", "DEPRECATED"}
RUN_STATUSES = {
    "PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK",
    "COMPLETED", "FAILED", "CANCELLED",
}
NODE_STATUSES = {
    "PENDING", "READY", "RUNNING", "WAITING_APPROVAL", "COMPLETED",
    "SKIPPED", "FAILED", "ROLLING_BACK", "ROLLED_BACK", "CANCELLED",
}
NODE_TYPES = {"TASK", "APPROVAL", "ROLLBACK"}


class SOPTemplate(Base):
    __tablename__ = "sop_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(String(3000), default="")
    category: Mapped[str] = mapped_column(String(100), default="General", index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    owner_identity: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SOPVersion(Base):
    __tablename__ = "sop_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(String(100), index=True)
    version_number: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    changelog: Mapped[str] = mapped_column(String(3000), default="")
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SOPRun(Base):
    __tablename__ = "sop_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(String(100), index=True)
    version_key: Mapped[str] = mapped_column(String(120), index=True)
    mission_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_by: Mapped[str] = mapped_column(String(180))
    failure_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    current_node_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SOPNodeRun(Base):
    __tablename__ = "sop_node_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_run_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    run_key: Mapped[str] = mapped_column(String(100), index=True)
    node_key: Mapped[str] = mapped_column(String(100), index=True)
    node_type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    task_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SOPRollbackDefinition(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    target_identity: str | None = Field(default=None, max_length=160)
    target_runtime_key: str | None = Field(default=None, max_length=80)
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    required_tools: list[str] = Field(default_factory=list, max_length=100)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)


class SOPNodeDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9._-]*$")
    title: str = Field(min_length=3, max_length=240)
    node_type: str = Field(default="TASK", pattern="^(TASK|APPROVAL)$")
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    objective: str = Field(default="", max_length=3000)
    source_identity: str = Field(default="service:sop", min_length=3, max_length=160)
    target_identity: str | None = Field(default=None, max_length=160)
    target_runtime_key: str | None = Field(default=None, max_length=80)
    routing_mode: str = Field(default="AUTO", pattern="^(AUTO|BEST|FAILOVER|FIXED)$")
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    review_policy: str = Field(default="AUTO", pattern="^(AUTO|HUMAN)$")
    auto_dispatch: bool = True
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=100)
    required_tools: list[str] = Field(default_factory=list, max_length=100)
    required_clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    preferred_department: str | None = Field(default=None, max_length=100)
    maximum_cost_usd: float | None = Field(default=None, ge=0.0, le=1000000.0)
    estimated_tokens: int | None = Field(default=None, ge=1, le=10000000)
    expected_outputs: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    inputs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    deadline_minutes: int | None = Field(default=None, ge=1, le=525600)
    verification_required: bool = True
    rollback: SOPRollbackDefinition | None = None

    @model_validator(mode="after")
    def validate_node(self):
        if self.node_type == "TASK" and len(self.objective.strip()) < 10:
            raise ValueError("TASK nodes require an objective of at least 10 characters")
        if self.node_type == "APPROVAL" and not self.objective.strip():
            self.objective = f"Approve or reject {self.title}."
        if self.routing_mode == "FIXED" and not self.target_runtime_key:
            raise ValueError("FIXED task nodes require target_runtime_key")
        return self


class SOPDefinition(BaseModel):
    nodes: list[SOPNodeDefinition] = Field(min_length=1, max_length=100)
    rollback_on_failure: bool = True
    stop_on_failure: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class SOPTemplateCreate(BaseModel):
    template_key: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9._-]*$")
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=3000)
    category: str = Field(default="General", min_length=2, max_length=100)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=50)
    definition: SOPDefinition
    changelog: str = Field(default="Initial draft", max_length=3000)


class SOPVersionCreate(BaseModel):
    definition: SOPDefinition
    changelog: str = Field(min_length=3, max_length=3000)


class SOPRunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    mission_title: str | None = Field(default=None, max_length=200)
    mission_priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    commander: str = Field(default="Beeza Commander", min_length=2, max_length=80)


class SOPNodeDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=2000)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def template_view(row: SOPTemplate) -> dict[str, Any]:
    return {
        "key": row.template_key,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "status": row.status,
        "current_version": row.current_version,
        "input_schema": row.input_schema,
        "tags": row.tags,
        "owner_identity": row.owner_identity,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def version_view(row: SOPVersion) -> dict[str, Any]:
    return {
        "key": row.version_key,
        "template_key": row.template_key,
        "version_number": row.version_number,
        "status": row.status,
        "definition": row.definition,
        "checksum": row.checksum,
        "changelog": row.changelog,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "published_at": iso(row.published_at),
    }


def run_view(row: SOPRun) -> dict[str, Any]:
    return {
        "key": row.run_key,
        "template_key": row.template_key,
        "version_key": row.version_key,
        "mission_key": row.mission_key,
        "status": row.status,
        "inputs": row.inputs,
        "outputs": row.outputs,
        "started_by": row.started_by,
        "failure_reason": row.failure_reason,
        "current_node_key": row.current_node_key,
        "started_at": iso(row.started_at),
        "ended_at": iso(row.ended_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def node_run_view(row: SOPNodeRun) -> dict[str, Any]:
    return {
        "key": row.node_run_key,
        "run_key": row.run_key,
        "node_key": row.node_key,
        "node_type": row.node_type,
        "status": row.status,
        "task_key": row.task_key,
        "attempt": row.attempt,
        "input": row.input_payload,
        "output": row.output_payload,
        "error": row.error,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
