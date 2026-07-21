from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base


class OutcomeRecord(Base):
    __tablename__ = "business_outcomes"
    __table_args__ = (
        UniqueConstraint("tenant_key", "task_key", name="uq_business_outcome_tenant_task"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outcome_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    task_key: Mapped[str] = mapped_column(String(100), index=True)
    department_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    agent_identity: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(100), default="General", index=True)
    status: Mapped[str] = mapped_column(String(30), default="VERIFIED", index=True)
    source_mode: Mapped[str] = mapped_column(String(30), default="ESTIMATED", index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    actual_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    hours_saved: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_saved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    revenue_value_usd: Mapped[float] = mapped_column(Float, default=0.0)
    sla_target_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    sla_met: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    result_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutiveSnapshot(Base):
    __tablename__ = "business_executive_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    department_scorecards: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    agent_economics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    integrity_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class BillingPlan(Base):
    __tablename__ = "business_billing_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    monthly_price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    included_units: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    overage_rates: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    deployment_mode: Mapped[str] = mapped_column(String(40), default="PRIVATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TenantSubscription(Base):
    __tablename__ = "business_tenant_subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_key", name="uq_business_subscription_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    plan_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    billing_day: Mapped[int] = mapped_column(Integer, default=1)
    contract_value_usd: Mapped[float] = mapped_column(Float, default=0.0)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageDaily(Base):
    __tablename__ = "business_usage_daily"
    __table_args__ = (
        UniqueConstraint("tenant_key", "usage_date", "meter", name="uq_business_usage_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    meter: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IndustryPack(Base):
    __tablename__ = "business_industry_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    industry: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    status: Mapped[str] = mapped_column(String(30), default="PUBLISHED", index=True)
    description: Mapped[str] = mapped_column(String(3000), default="")
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    sop_templates: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_connectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PackInstallation(Base):
    __tablename__ = "business_pack_installations"
    __table_args__ = (
        UniqueConstraint("tenant_key", "pack_key", name="uq_business_pack_installation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    pack_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="INSTALLED", index=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    installed_by: Mapped[str] = mapped_column(String(180))
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutcomeUpsert(BaseModel):
    mission_key: str = Field(min_length=3, max_length=80)
    task_key: str = Field(min_length=3, max_length=100)
    department_key: str | None = Field(default=None, max_length=100)
    agent_identity: str | None = Field(default=None, max_length=180)
    category: str = Field(default="General", min_length=2, max_length=100)
    status: str = Field(default="VERIFIED", pattern="^(VERIFIED|REVIEW|FAILED|VOID)$")
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_count: int = Field(default=0, ge=0, le=100000)
    baseline_minutes: float = Field(default=0.0, ge=0.0, le=10000000.0)
    actual_minutes: float = Field(default=0.0, ge=0.0, le=10000000.0)
    baseline_cost_usd: float = Field(default=0.0, ge=0.0, le=1000000000.0)
    actual_cost_usd: float = Field(default=0.0, ge=0.0, le=1000000000.0)
    revenue_value_usd: float = Field(default=0.0, ge=0.0, le=1000000000.0)
    sla_target_minutes: float = Field(default=0.0, ge=0.0, le=10000000.0)
    result_hash: str = Field(default="", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionCreate(BaseModel):
    plan_key: str = Field(min_length=3, max_length=100)
    contract_value_usd: float = Field(default=0.0, ge=0.0, le=1000000000.0)
    currency: str = Field(default="USD", min_length=3, max_length=10)
    billing_day: int = Field(default=1, ge=1, le=28)
    settings: dict[str, Any] = Field(default_factory=dict)


class PackInstallCreate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class SnapshotCreate(BaseModel):
    days: int = Field(default=30, ge=1, le=3660)
