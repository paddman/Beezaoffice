from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

EVALUATION_STATUSES = {"PASS", "WARN", "FAIL", "ERROR"}
EVALUATION_RECOMMENDATIONS = {
    "AUTO_ACCEPT", "HUMAN_ACCEPT", "HUMAN_REVIEW", "REVISE_OR_REPLAY", "INVESTIGATE",
}
REPLAY_STATUSES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
REPLAY_MODES = {"SAME", "REROUTE", "FAILOVER"}


class EvaluationPolicy(Base):
    __tablename__ = "evaluation_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    pass_score: Mapped[float] = mapped_column(Float, default=0.78)
    warn_score: Mapped[float] = mapped_column(Float, default=0.55)
    minimum_evidence: Mapped[int] = mapped_column(Integer, default=2)
    require_provenance: Mapped[bool] = mapped_column(Boolean, default=True)
    require_acceptance_coverage: Mapped[bool] = mapped_column(Boolean, default=True)
    reopen_failed_auto_tasks: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    task_key: Mapped[str] = mapped_column(String(100), index=True)
    policy_key: Mapped[str] = mapped_column(String(100), index=True)
    evaluator_identity: Mapped[str] = mapped_column(String(180), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    score: Mapped[float] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(40), index=True)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_status: Mapped[str] = mapped_column(String(40))
    source_dispatch_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    components: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceRecord(Base):
    __tablename__ = "evaluation_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    evaluation_key: Mapped[str] = mapped_column(String(100), index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    task_key: Mapped[str] = mapped_column(String(100), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(240))
    locator: Mapped[str] = mapped_column(String(1000), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplayRun(Base):
    __tablename__ = "evaluation_replays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replay_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    source_task_key: Mapped[str] = mapped_column(String(100), index=True)
    replay_task_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    mode: Mapped[str] = mapped_column(String(30), default="REROUTE")
    requested_by: Mapped[str] = mapped_column(String(180))
    reason: Mapped[str] = mapped_column(String(2000))
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationPolicyUpdate(BaseModel):
    enabled: bool | None = None
    weights: dict[str, float] | None = None
    pass_score: float | None = Field(default=None, ge=0.0, le=1.0)
    warn_score: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_evidence: int | None = Field(default=None, ge=0, le=100)
    require_provenance: bool | None = None
    require_acceptance_coverage: bool | None = None
    reopen_failed_auto_tasks: bool | None = None
    settings: dict[str, Any] | None = None


class EvaluationRequest(BaseModel):
    force: bool = False
    note: str | None = Field(default=None, max_length=2000)


class ReplayCreate(BaseModel):
    source_task_key: str = Field(min_length=3, max_length=100)
    mode: str = Field(default="REROUTE", pattern="^(SAME|REROUTE|FAILOVER)$")
    reason: str = Field(min_length=3, max_length=2000)
    preferred_runtime_key: str | None = Field(default=None, max_length=80)
    target_identity: str | None = Field(default=None, max_length=160)
    auto_dispatch: bool = True


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def policy_view(row: EvaluationPolicy) -> dict[str, Any]:
    return {
        "key": row.policy_key,
        "name": row.name,
        "enabled": row.enabled,
        "weights": row.weights,
        "pass_score": row.pass_score,
        "warn_score": row.warn_score,
        "minimum_evidence": row.minimum_evidence,
        "require_provenance": row.require_provenance,
        "require_acceptance_coverage": row.require_acceptance_coverage,
        "reopen_failed_auto_tasks": row.reopen_failed_auto_tasks,
        "settings": row.settings,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def evaluation_view(row: EvaluationRun) -> dict[str, Any]:
    return {
        "key": row.evaluation_key,
        "mission_key": row.mission_key,
        "task_key": row.task_key,
        "policy_key": row.policy_key,
        "evaluator_identity": row.evaluator_identity,
        "status": row.status,
        "score": row.score,
        "recommendation": row.recommendation,
        "result_hash": row.result_hash,
        "source_status": row.source_status,
        "source_dispatch_key": row.source_dispatch_key,
        "components": row.components,
        "findings": row.findings,
        "evidence_count": row.evidence_count,
        "snapshot": row.snapshot,
        "created_at": iso(row.created_at),
    }


def evidence_view(row: EvidenceRecord) -> dict[str, Any]:
    return {
        "key": row.evidence_key,
        "evaluation_key": row.evaluation_key,
        "mission_key": row.mission_key,
        "task_key": row.task_key,
        "type": row.evidence_type,
        "title": row.title,
        "locator": row.locator,
        "content_hash": row.content_hash,
        "strength": row.strength,
        "metadata": row.metadata_json,
        "created_at": iso(row.created_at),
    }


def replay_view(row: ReplayRun) -> dict[str, Any]:
    return {
        "key": row.replay_key,
        "mission_key": row.mission_key,
        "source_task_key": row.source_task_key,
        "replay_task_key": row.replay_task_key,
        "status": row.status,
        "mode": row.mode,
        "requested_by": row.requested_by,
        "reason": row.reason,
        "source_snapshot": row.source_snapshot,
        "comparison": row.comparison,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
