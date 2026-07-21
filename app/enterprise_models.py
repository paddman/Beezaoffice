from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base


class EnterpriseTenant(Base):
    __tablename__ = "enterprise_tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    isolation_mode: Mapped[str] = mapped_column(String(30), default="ROW", index=True)
    data_region: Mapped[str] = mapped_column(String(100), default="on-premises")
    namespace: Mapped[str] = mapped_column(String(100), default="beezaoffice")
    object_store_bucket: Mapped[str] = mapped_column(String(180), default="beeza-evidence")
    encryption_key_ref: Mapped[str] = mapped_column(String(500), default="")
    max_agents: Mapped[int] = mapped_column(Integer, default=1000)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=200)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=600)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    air_gapped: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityProvider(Base):
    __tablename__ = "enterprise_identity_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    provider_type: Mapped[str] = mapped_column(String(30), default="OIDC", index=True)
    issuer_url: Mapped[str] = mapped_column(String(500), default="")
    client_id: Mapped[str] = mapped_column(String(300), default="")
    audience: Mapped[str] = mapped_column(String(300), default="")
    jwks_uri: Mapped[str] = mapped_column(String(500), default="")
    authorization_endpoint: Mapped[str] = mapped_column(String(500), default="")
    token_endpoint: Mapped[str] = mapped_column(String(500), default="")
    allowed_algorithms: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["RS256"])
    subject_claim: Mapped[str] = mapped_column(String(100), default="sub")
    email_claim: Mapped[str] = mapped_column(String(100), default="email")
    groups_claim: Mapped[str] = mapped_column(String(100), default="groups")
    role_map: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    default_role_key: Mapped[str] = mapped_column(String(100), default="role:operator")
    auto_provision: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnterpriseMembership(Base):
    __tablename__ = "enterprise_memberships"
    __table_args__ = (
        UniqueConstraint("provider_key", "external_subject", name="uq_enterprise_provider_subject"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    membership_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    provider_key: Mapped[str] = mapped_column(String(100), index=True)
    external_subject: Mapped[str] = mapped_column(String(500), index=True)
    identity_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), default="", index=True)
    groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnterpriseSession(Base):
    __tablename__ = "enterprise_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    identity_key: Mapped[str] = mapped_column(String(180), index=True)
    provider_key: Mapped[str] = mapped_column(String(100), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnterpriseApiKey(Base):
    __tablename__ = "enterprise_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(32), index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    identity_key: Mapped[str] = mapped_column(String(180), index=True)
    name: Mapped[str] = mapped_column(String(200))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=300)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResourceScope(Base):
    __tablename__ = "enterprise_resource_scopes"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_key", name="uq_enterprise_resource_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(60), index=True)
    resource_key: Mapped[str] = mapped_column(String(180), index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    namespace: Mapped[str] = mapped_column(String(120), default="default")
    classification: Mapped[str] = mapped_column(String(30), default="INTERNAL")
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeploymentSite(Base):
    __tablename__ = "enterprise_deployment_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    site_type: Mapped[str] = mapped_column(String(30), default="PRIMARY", index=True)
    region: Mapped[str] = mapped_column(String(100), default="on-premises")
    status: Mapped[str] = mapped_column(String(30), default="READY", index=True)
    rpo_minutes: Mapped[int] = mapped_column(Integer, default=15)
    rto_minutes: Mapped[int] = mapped_column(Integer, default=60)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BackupPlan(Base):
    __tablename__ = "enterprise_backup_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    schedule: Mapped[str] = mapped_column(String(120), default="0 2 * * *")
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    targets: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["postgres", "redis", "evidence"])
    destination: Mapped[str] = mapped_column(String(500), default="s3://beeza-backups")
    encryption_key_ref: Mapped[str] = mapped_column(String(500), default="")
    immutable: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BackupRun(Base):
    __tablename__ = "enterprise_backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    plan_key: Mapped[str] = mapped_column(String(100), index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(40), default="REQUESTED", index=True)
    mode: Mapped[str] = mapped_column(String(30), default="FULL")
    executor: Mapped[str] = mapped_column(String(180), default="external-backup-runner")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SIEMSink(Base):
    __tablename__ = "enterprise_siem_sinks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sink_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sink_type: Mapped[str] = mapped_column(String(30), default="HTTP", index=True)
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    format: Mapped[str] = mapped_column(String(30), default="JSONL")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_audit_id: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=2, max_length=200)
    data_region: str = Field(default="on-premises", max_length=100)
    isolation_mode: str = Field(default="ROW", pattern="^(ROW|SCHEMA|DATABASE)$")
    max_agents: int = Field(default=1000, ge=1, le=100000)
    max_concurrent_tasks: int = Field(default=200, ge=1, le=100000)
    requests_per_minute: int = Field(default=600, ge=10, le=1000000)
    air_gapped: bool = False


class IdentityProviderCreate(BaseModel):
    tenant_key: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    provider_type: str = Field(default="OIDC", pattern="^(OIDC|SAML|LDAP)$")
    issuer_url: str = Field(default="", max_length=500)
    client_id: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=300)
    jwks_uri: str = Field(default="", max_length=500)
    default_role_key: str = Field(default="role:operator", max_length=100)
    role_map: dict[str, str] = Field(default_factory=dict)
    auto_provision: bool = True
    enabled: bool = False


class OIDCExchange(BaseModel):
    provider_key: str = Field(min_length=3, max_length=100)
    id_token: str = Field(min_length=20, max_length=20000)
    session_minutes: int = Field(default=480, ge=5, le=10080)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    identity_key: str = Field(min_length=3, max_length=180)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    rate_limit_per_minute: int = Field(default=300, ge=10, le=100000)
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


class BackupPlanCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    schedule: str = Field(default="0 2 * * *", min_length=5, max_length=120)
    retention_days: int = Field(default=30, ge=1, le=3650)
    targets: list[str] = Field(default_factory=lambda: ["postgres", "redis", "evidence"], max_length=20)
    destination: str = Field(default="s3://beeza-backups", min_length=3, max_length=500)
    encryption_key_ref: str = Field(default="", max_length=500)
    immutable: bool = True


class BackupRunComplete(BaseModel):
    status: str = Field(pattern="^(COMPLETED|FAILED|PARTIAL)$")
    manifest: dict[str, Any] = Field(default_factory=dict)
    checksum: str = Field(default="", max_length=64)
    error: str | None = Field(default=None, max_length=2000)


class SIEMSinkCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    sink_type: str = Field(default="HTTP", pattern="^(HTTP|SYSLOG|FILE)$")
    endpoint: str = Field(default="", max_length=500)
    format: str = Field(default="JSONL", pattern="^(JSONL|CEF|LEEF)$")
    enabled: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)
