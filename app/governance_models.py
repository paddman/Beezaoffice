from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

IDENTITY_TYPES = {"HUMAN", "AGENT", "SERVICE", "RUNTIME"}
IDENTITY_STATUSES = {"ACTIVE", "SUSPENDED", "REVOKED"}
CLEARANCE_LEVELS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
POLICY_EFFECTS = {"ALLOW", "DENY", "APPROVAL"}
APPROVAL_STATUSES = {"PENDING", "APPROVED", "DENIED", "EXPIRED", "USED"}
BUDGET_ENTRY_TYPES = {"RESERVE", "CHARGE", "RELEASE", "ADJUST"}


class Tenant(Base):
    __tablename__ = "governance_tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    data_region: Mapped[str] = mapped_column(String(100), default="on-premises")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Department(Base):
    __tablename__ = "governance_departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_department_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    risk_tier: Mapped[str] = mapped_column(String(30), default="NORMAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GovernanceIdentity(Base):
    __tablename__ = "governance_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    identity_type: Mapped[str] = mapped_column(String(30), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    department_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    clearance: Mapped[str] = mapped_column(String(30), default="INTERNAL")
    daily_budget_usd: Mapped[float] = mapped_column(Float, default=50.0)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=1000.0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GovernanceRole(Base):
    __tablename__ = "governance_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(1200), default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    system_role: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RoleBinding(Base):
    __tablename__ = "governance_role_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    binding_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    identity_key: Mapped[str] = mapped_column(String(180), index=True)
    role_key: Mapped[str] = mapped_column(String(100), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), default="GLOBAL")
    scope_key: Mapped[str] = mapped_column(String(180), default="*")
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyRule(Base):
    __tablename__ = "governance_policy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    action_pattern: Mapped[str] = mapped_column(String(180), index=True)
    effect: Mapped[str] = mapped_column(String(30), index=True)
    risk_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    minimum_clearance: Mapped[str] = mapped_column(String(30), default="PUBLIC")
    maximum_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRequest(Base):
    __tablename__ = "governance_approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    action: Mapped[str] = mapped_column(String(180), index=True)
    requester_identity: Mapped[str] = mapped_column(String(180), index=True)
    target: Mapped[str] = mapped_column(String(500), default="")
    mission_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    risk_level: Mapped[str] = mapped_column(String(30), default="HIGH")
    reason: Mapped[str] = mapped_column(String(2000))
    payload_hash: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(180), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetLedger(Base):
    __tablename__ = "governance_budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ledger_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    identity_key: Mapped[str] = mapped_column(String(180), index=True)
    mission_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(180), index=True)
    entry_type: Mapped[str] = mapped_column(String(30), index=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    reference_key: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuditRecord(Base):
    __tablename__ = "governance_audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    identity_key: Mapped[str] = mapped_column(String(180), index=True)
    action: Mapped[str] = mapped_column(String(180), index=True)
    method: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(String(1000))
    resource: Mapped[str] = mapped_column(String(500), default="")
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_ip: Mapped[str] = mapped_column(String(100), default="")
    user_agent: Mapped[str] = mapped_column(String(500), default="")
    previous_hash: Mapped[str] = mapped_column(String(128), default="GENESIS")
    record_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SystemControl(Base):
    __tablename__ = "governance_system_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    control_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(String(2000), default="")
    changed_by: Mapped[str] = mapped_column(String(180))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityCreate(BaseModel):
    identity_key: str = Field(min_length=3, max_length=180)
    display_name: str = Field(min_length=2, max_length=200)
    identity_type: str = Field(pattern="^(HUMAN|AGENT|SERVICE|RUNTIME)$")
    tenant_key: str = Field(default="tenant:beeza", min_length=3, max_length=100)
    department_key: str | None = Field(default=None, max_length=100)
    clearance: str = Field(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    daily_budget_usd: float = Field(default=50.0, ge=0, le=1_000_000)
    monthly_budget_usd: float = Field(default=1000.0, ge=0, le=10_000_000)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RoleBindingCreate(BaseModel):
    identity_key: str = Field(min_length=3, max_length=180)
    role_key: str = Field(min_length=2, max_length=100)
    scope_type: str = Field(default="GLOBAL", pattern="^(GLOBAL|TENANT|DEPARTMENT|MISSION)$")
    scope_key: str = Field(default="*", min_length=1, max_length=180)


class PolicyRuleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    action_pattern: str = Field(min_length=1, max_length=180)
    effect: str = Field(pattern="^(ALLOW|DENY|APPROVAL)$")
    risk_levels: list[str] = Field(default_factory=list, max_length=10)
    minimum_clearance: str = Field(default="PUBLIC", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    maximum_cost_usd: float | None = Field(default=None, ge=0)
    priority: int = Field(default=100, ge=0, le=10_000)
    conditions: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequestCreate(BaseModel):
    action: str = Field(min_length=2, max_length=180)
    target: str = Field(default="", max_length=500)
    mission_key: str | None = Field(default=None, max_length=80)
    risk_level: str = Field(default="HIGH", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")
    reason: str = Field(min_length=5, max_length=2000)
    payload_hash: str = Field(default="", max_length=128)
    expires_in_minutes: int = Field(default=60, ge=1, le=10_080)


class ApprovalDecisionCreate(BaseModel):
    decision: str = Field(pattern="^(APPROVED|DENIED)$")
    note: str = Field(default="", max_length=2000)


class KillSwitchUpdate(BaseModel):
    execution_enabled: bool
    reason: str = Field(min_length=3, max_length=2000)


class BudgetChargeCreate(BaseModel):
    identity_key: str = Field(min_length=3, max_length=180)
    mission_key: str | None = Field(default=None, max_length=80)
    action: str = Field(min_length=2, max_length=180)
    amount_usd: float = Field(gt=0, le=1_000_000)
    reference_key: str | None = Field(default=None, max_length=180)
    details: dict[str, Any] = Field(default_factory=dict)
