from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

REGISTRY_STATUSES = {"ACTIVE", "SUSPENDED", "RETIRED"}
AVAILABILITY_STATES = {"AVAILABLE", "BUSY", "WAITING", "OFFLINE", "MAINTENANCE"}
DELEGATION_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}


class RegisteredAgent(Base):
    __tablename__ = "agent_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    identity_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), index=True)
    role_title: Mapped[str] = mapped_column(String(200))
    department_key: Mapped[str] = mapped_column(String(100), index=True)
    manager_agent_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    availability: Mapped[str] = mapped_column(String(30), default="AVAILABLE", index=True)
    preferred_runtime_key: Mapped[str] = mapped_column(String(80), default="cherryagent", index=True)
    preferred_model: Mapped[str] = mapped_column(String(180), default="")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    current_workload: Mapped[int] = mapped_column(Integer, default=0)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.90)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_clearance: Mapped[str] = mapped_column(String(30), default="INTERNAL")
    version: Mapped[str] = mapped_column(String(80), default="1.0.0")
    owner_identity: Mapped[str] = mapped_column(String(180), default="human:owner")
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentDelegation(Base):
    __tablename__ = "agent_delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegation_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_agent_key: Mapped[str] = mapped_column(String(120), index=True)
    target_agent_key: Mapped[str] = mapped_column(String(120), index=True)
    scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentCreate(BaseModel):
    agent_key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    identity_key: str = Field(min_length=3, max_length=180)
    display_name: str = Field(min_length=2, max_length=160)
    role_title: str = Field(min_length=2, max_length=200)
    department_key: str = Field(min_length=3, max_length=100)
    manager_agent_key: str | None = Field(default=None, max_length=120)
    preferred_runtime_key: str = Field(default="cherryagent", min_length=2, max_length=80)
    preferred_model: str = Field(default="", max_length=180)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    skills: list[str] = Field(default_factory=list, max_length=100)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    allowed_tools: list[str] = Field(default_factory=list, max_length=200)
    data_clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    version: str = Field(default="1.0.0", min_length=1, max_length=80)
    owner_identity: str = Field(default="human:owner", min_length=3, max_length=180)
    profile: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    role_title: str | None = Field(default=None, min_length=2, max_length=200)
    department_key: str | None = Field(default=None, min_length=3, max_length=100)
    manager_agent_key: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, pattern="^(ACTIVE|SUSPENDED|RETIRED)$")
    availability: str | None = Field(default=None, pattern="^(AVAILABLE|BUSY|WAITING|OFFLINE|MAINTENANCE)$")
    preferred_runtime_key: str | None = Field(default=None, min_length=2, max_length=80)
    preferred_model: str | None = Field(default=None, max_length=180)
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    reliability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    skills: list[str] | None = Field(default=None, max_length=100)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    allowed_tools: list[str] | None = Field(default=None, max_length=200)
    data_clearance: str | None = Field(default=None, pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    version: str | None = Field(default=None, min_length=1, max_length=80)
    owner_identity: str | None = Field(default=None, min_length=3, max_length=180)
    profile: dict[str, Any] | None = None


class AgentHeartbeat(BaseModel):
    availability: str = Field(default="AVAILABLE", pattern="^(AVAILABLE|BUSY|WAITING|OFFLINE|MAINTENANCE)$")
    current_workload: int | None = Field(default=None, ge=0, le=1000)
    successful_runs_delta: int = Field(default=0, ge=0, le=10000)
    failed_runs_delta: int = Field(default=0, ge=0, le=10000)
    profile_patch: dict[str, Any] = Field(default_factory=dict)


class DelegationCreate(BaseModel):
    source_agent_key: str = Field(min_length=2, max_length=120)
    target_agent_key: str = Field(min_length=2, max_length=120)
    scope: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)
    ends_at: datetime | None = None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def agent_view(row: RegisteredAgent) -> dict[str, Any]:
    capacity = max(0, row.max_concurrency - row.current_workload)
    return {
        "key": row.agent_key,
        "identity_key": row.identity_key,
        "name": row.display_name,
        "role": row.role_title,
        "department_key": row.department_key,
        "manager_agent_key": row.manager_agent_key,
        "status": row.status,
        "availability": row.availability,
        "preferred_runtime_key": row.preferred_runtime_key,
        "preferred_model": row.preferred_model,
        "max_concurrency": row.max_concurrency,
        "current_workload": row.current_workload,
        "available_capacity": capacity,
        "utilization": round(row.current_workload / row.max_concurrency, 4) if row.max_concurrency else 0.0,
        "reliability_score": row.reliability_score,
        "successful_runs": row.successful_runs,
        "failed_runs": row.failed_runs,
        "total_runs": row.total_runs,
        "skills": row.skills,
        "capabilities": row.capabilities,
        "allowed_tools": row.allowed_tools,
        "data_clearance": row.data_clearance,
        "version": row.version,
        "owner_identity": row.owner_identity,
        "profile": row.profile,
        "last_heartbeat_at": iso(row.last_heartbeat_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def delegation_view(row: AgentDelegation) -> dict[str, Any]:
    return {
        "key": row.delegation_key,
        "source_agent_key": row.source_agent_key,
        "target_agent_key": row.target_agent_key,
        "scope": row.scope,
        "reason": row.reason,
        "status": row.status,
        "starts_at": iso(row.starts_at),
        "ends_at": iso(row.ends_at),
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
