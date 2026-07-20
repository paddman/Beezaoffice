from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

ROUTING_DECISION_STATUSES = {"SELECTED", "WAITING", "NO_ROUTE", "OVERRIDDEN"}
ROUTING_MODES = {"AUTO", "BEST", "FAILOVER", "FIXED"}


class SchedulerPolicy(Base):
    __tablename__ = "scheduler_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    runtime_limits: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    runtime_cost_per_1k_tokens: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    default_token_estimate: Mapped[int] = mapped_column(Integer, default=4000)
    minimum_score: Mapped[float] = mapped_column(Float, default=0.35)
    minimum_skill_coverage: Mapped[float] = mapped_column(Float, default=0.50)
    max_route_attempts: Mapped[int] = mapped_column(Integer, default=5)
    retry_seconds: Mapped[int] = mapped_column(Integer, default=30)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    task_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    policy_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    selected_agent_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    selected_runtime_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    selected_model: Mapped[str | None] = mapped_column(String(180), nullable=True)
    selected_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RoutedTaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    objective: str = Field(min_length=10, max_length=3000)
    source_identity: str = Field(default="agent:Beeza Commander", min_length=3, max_length=160)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    review_policy: str = Field(default="AUTO", pattern="^(AUTO|HUMAN)$")
    auto_dispatch: bool = True
    routing_mode: str = Field(default="AUTO", pattern="^(AUTO|BEST|FAILOVER)$")
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=100)
    required_tools: list[str] = Field(default_factory=list, max_length=100)
    required_clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    preferred_department: str | None = Field(default=None, max_length=100)
    preferred_runtime_key: str | None = Field(default=None, max_length=80)
    maximum_cost_usd: float | None = Field(default=None, ge=0.0, le=1000000.0)
    estimated_tokens: int | None = Field(default=None, ge=1, le=10000000)
    strict_skills: bool = False
    allow_overflow: bool = False
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    inputs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    expected_outputs: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    context: dict[str, Any] = Field(default_factory=dict)
    deadline_at: datetime | None = None


class RoutingSimulation(BaseModel):
    objective: str = Field(min_length=5, max_length=3000)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=100)
    required_tools: list[str] = Field(default_factory=list, max_length=100)
    required_clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    preferred_department: str | None = Field(default=None, max_length=100)
    preferred_runtime_key: str | None = Field(default=None, max_length=80)
    maximum_cost_usd: float | None = Field(default=None, ge=0.0, le=1000000.0)
    estimated_tokens: int | None = Field(default=None, ge=1, le=10000000)
    strict_skills: bool = False
    allow_overflow: bool = False
    deadline_at: datetime | None = None
    excluded_agents: list[str] = Field(default_factory=list, max_length=100)
    excluded_runtimes: list[str] = Field(default_factory=list, max_length=50)


class SchedulerPolicyUpdate(BaseModel):
    enabled: bool | None = None
    weights: dict[str, float] | None = None
    runtime_limits: dict[str, int] | None = None
    runtime_cost_per_1k_tokens: dict[str, float] | None = None
    default_token_estimate: int | None = Field(default=None, ge=1, le=10000000)
    minimum_score: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_skill_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    max_route_attempts: int | None = Field(default=None, ge=1, le=100)
    retry_seconds: int | None = Field(default=None, ge=2, le=86400)
    settings: dict[str, Any] | None = None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def policy_view(row: SchedulerPolicy) -> dict[str, Any]:
    return {
        "key": row.policy_key,
        "name": row.name,
        "enabled": row.enabled,
        "weights": row.weights,
        "runtime_limits": row.runtime_limits,
        "runtime_cost_per_1k_tokens": row.runtime_cost_per_1k_tokens,
        "default_token_estimate": row.default_token_estimate,
        "minimum_score": row.minimum_score,
        "minimum_skill_coverage": row.minimum_skill_coverage,
        "max_route_attempts": row.max_route_attempts,
        "retry_seconds": row.retry_seconds,
        "settings": row.settings,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def decision_view(row: RoutingDecision) -> dict[str, Any]:
    return {
        "key": row.decision_key,
        "mission_key": row.mission_key,
        "task_key": row.task_key,
        "policy_key": row.policy_key,
        "status": row.status,
        "attempt": row.attempt,
        "selected_agent_key": row.selected_agent_key,
        "selected_runtime_key": row.selected_runtime_key,
        "selected_model": row.selected_model,
        "selected_score": row.selected_score,
        "requested": row.requested,
        "candidates": row.candidates,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
    }
