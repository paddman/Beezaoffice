from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from main import Base

ONBOARDING_STATUSES = {"DRAFT", "IN_PROGRESS", "READY", "COMPLETED", "CANCELLED"}
LICENSE_STATUSES = {"ACTIVE", "EXPIRED", "INVALID", "REVOKED", "DEVELOPMENT"}
DEPLOYMENT_STATUSES = {"REGISTERED", "ACTIVE", "DEGRADED", "OFFLINE", "REVOKED"}
RELEASE_STATUSES = {"DRAFT", "PUBLISHED", "DEPRECATED", "REVOKED", "UNSIGNED"}
LICENSE_MODES = {"development", "warn", "enforce"}


class TenantOnboarding(Base):
    __tablename__ = "commercial_onboarding"
    __table_args__ = (
        UniqueConstraint("tenant_key", name="uq_commercial_onboarding_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    onboarding_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    organization_name: Mapped[str] = mapped_column(String(240))
    primary_contact: Mapped[str] = mapped_column(String(320), default="")
    requested_plan: Mapped[str] = mapped_column(String(100), default="plan:enterprise")
    deployment_mode: Mapped[str] = mapped_column(String(40), default="PRIVATE")
    desired_domain: Mapped[str] = mapped_column(String(240), default="")
    data_region: Mapped[str] = mapped_column(String(100), default="on-premises")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    current_step: Mapped[str] = mapped_column(String(80), default="organization")
    checklist: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CommercialLicense(Base):
    __tablename__ = "commercial_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    license_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    deployment_id: Mapped[str] = mapped_column(String(180), index=True)
    plan_key: Mapped[str] = mapped_column(String(100), default="plan:enterprise", index=True)
    status: Mapped[str] = mapped_column(String(30), default="INVALID", index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    issuer: Mapped[str] = mapped_column(String(240), default="")
    subject: Mapped[str] = mapped_column(String(240), default="")
    signature_algorithm: Mapped[str] = mapped_column(String(30), default="")
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    limits: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    claims: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    activated_by: Mapped[str] = mapped_column(String(180))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeatureEntitlement(Base):
    __tablename__ = "commercial_feature_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_key",
            "feature_key",
            "source",
            name="uq_commercial_tenant_feature_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entitlement_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    feature_key: Mapped[str] = mapped_column(String(140), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="LICENSE", index=True)
    source_key: Mapped[str] = mapped_column(String(120), default="")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BrandProfile(Base):
    __tablename__ = "commercial_brand_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_key", name="uq_commercial_brand_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    product_name: Mapped[str] = mapped_column(String(160), default="BeezaOffice")
    company_name: Mapped[str] = mapped_column(String(240), default="BeezaOffice")
    logo_url: Mapped[str] = mapped_column(String(1000), default="")
    favicon_url: Mapped[str] = mapped_column(String(1000), default="")
    primary_color: Mapped[str] = mapped_column(String(20), default="#dc285c")
    accent_color: Mapped[str] = mapped_column(String(20), default="#1677ff")
    background_color: Mapped[str] = mapped_column(String(20), default="#ffffff")
    support_url: Mapped[str] = mapped_column(String(1000), default="")
    privacy_url: Mapped[str] = mapped_column(String(1000), default="")
    terms_url: Mapped[str] = mapped_column(String(1000), default="")
    custom_domain: Mapped[str] = mapped_column(String(240), default="")
    locale: Mapped[str] = mapped_column(String(20), default="en")
    email_from: Mapped[str] = mapped_column(String(320), default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(180))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeploymentActivation(Base):
    __tablename__ = "commercial_deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_key: Mapped[str] = mapped_column(String(100), index=True)
    deployment_id: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(40), default="production")
    hostname: Mapped[str] = mapped_column(String(240), default="")
    site: Mapped[str] = mapped_column(String(160), default="primary")
    version: Mapped[str] = mapped_column(String(40), default="")
    image_digest: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(30), default="REGISTERED", index=True)
    license_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    registered_by: Mapped[str] = mapped_column(String(180))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ReleaseManifest(Base):
    __tablename__ = "commercial_release_manifests"
    __table_args__ = (
        UniqueConstraint("version", "channel", name="uq_commercial_release_version_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="stable", index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    image_ref: Mapped[str] = mapped_column(String(500))
    image_digest: Mapped[str] = mapped_column(String(180), default="")
    signature_ref: Mapped[str] = mapped_column(String(1000), default="")
    sbom_ref: Mapped[str] = mapped_column(String(1000), default="")
    provenance_ref: Mapped[str] = mapped_column(String(1000), default="")
    minimum_plan: Mapped[str] = mapped_column(String(100), default="plan:team")
    notes: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingCreate(BaseModel):
    organization_name: str = Field(min_length=2, max_length=240)
    primary_contact: str = Field(default="", max_length=320)
    requested_plan: str = Field(default="plan:enterprise", min_length=3, max_length=100)
    deployment_mode: str = Field(default="PRIVATE", pattern="^(PRIVATE|ENTERPRISE|SOVEREIGN|SAAS)$")
    desired_domain: str = Field(default="", max_length=240)
    data_region: str = Field(default="on-premises", min_length=2, max_length=100)
    settings: dict[str, Any] = Field(default_factory=dict)


class OnboardingAdvance(BaseModel):
    step: str = Field(min_length=2, max_length=80)
    completed: bool = True
    note: str = Field(default="", max_length=1000)


class LicenseImport(BaseModel):
    token: str = Field(min_length=40, max_length=20000)


class BrandUpdate(BaseModel):
    product_name: str | None = Field(default=None, min_length=2, max_length=160)
    company_name: str | None = Field(default=None, min_length=2, max_length=240)
    logo_url: str | None = Field(default=None, max_length=1000)
    favicon_url: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    support_url: str | None = Field(default=None, max_length=1000)
    privacy_url: str | None = Field(default=None, max_length=1000)
    terms_url: str | None = Field(default=None, max_length=1000)
    custom_domain: str | None = Field(default=None, max_length=240)
    locale: str | None = Field(default=None, min_length=2, max_length=20)
    email_from: str | None = Field(default=None, max_length=320)
    settings: dict[str, Any] | None = None


class DeploymentRegister(BaseModel):
    deployment_id: str = Field(min_length=3, max_length=180)
    fingerprint: str = Field(min_length=16, max_length=128)
    environment: str = Field(default="production", pattern="^(development|staging|production|dr)$")
    hostname: str = Field(default="", max_length=240)
    site: str = Field(default="primary", max_length=160)
    version: str = Field(default="", max_length=40)
    image_digest: str = Field(default="", max_length=180)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeploymentHeartbeat(BaseModel):
    status: str = Field(default="ACTIVE", pattern="^(REGISTERED|ACTIVE|DEGRADED|OFFLINE|REVOKED)$")
    version: str | None = Field(default=None, max_length=40)
    image_digest: str | None = Field(default=None, max_length=180)
    metadata: dict[str, Any] = Field(default_factory=dict)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def onboarding_view(row: TenantOnboarding) -> dict[str, Any]:
    return {
        "key": row.onboarding_key,
        "tenant_key": row.tenant_key,
        "organization_name": row.organization_name,
        "primary_contact": row.primary_contact,
        "requested_plan": row.requested_plan,
        "deployment_mode": row.deployment_mode,
        "desired_domain": row.desired_domain,
        "data_region": row.data_region,
        "status": row.status,
        "current_step": row.current_step,
        "checklist": row.checklist,
        "settings": row.settings,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "completed_at": iso(row.completed_at),
    }


def license_view(row: CommercialLicense) -> dict[str, Any]:
    return {
        "key": row.license_key,
        "tenant_key": row.tenant_key,
        "deployment_id": row.deployment_id,
        "plan_key": row.plan_key,
        "status": row.status,
        "issuer": row.issuer,
        "subject": row.subject,
        "signature_algorithm": row.signature_algorithm,
        "features": row.features,
        "limits": row.limits,
        "not_before": iso(row.not_before),
        "expires_at": iso(row.expires_at),
        "activated_by": row.activated_by,
        "activated_at": iso(row.activated_at),
        "last_verified_at": iso(row.last_verified_at),
        "verification_error": row.verification_error,
    }


def entitlement_view(row: FeatureEntitlement) -> dict[str, Any]:
    return {
        "key": row.entitlement_key,
        "tenant_key": row.tenant_key,
        "feature_key": row.feature_key,
        "enabled": row.enabled,
        "limit_value": row.limit_value,
        "source": row.source,
        "source_key": row.source_key,
        "valid_from": iso(row.valid_from),
        "valid_until": iso(row.valid_until),
        "metadata": row.metadata_json,
        "updated_at": iso(row.updated_at),
    }


def brand_view(row: BrandProfile) -> dict[str, Any]:
    return {
        "tenant_key": row.tenant_key,
        "product_name": row.product_name,
        "company_name": row.company_name,
        "logo_url": row.logo_url,
        "favicon_url": row.favicon_url,
        "primary_color": row.primary_color,
        "accent_color": row.accent_color,
        "background_color": row.background_color,
        "support_url": row.support_url,
        "privacy_url": row.privacy_url,
        "terms_url": row.terms_url,
        "custom_domain": row.custom_domain,
        "locale": row.locale,
        "email_from": row.email_from,
        "settings": row.settings,
        "updated_by": row.updated_by,
        "updated_at": iso(row.updated_at),
    }


def deployment_view(row: DeploymentActivation) -> dict[str, Any]:
    return {
        "key": row.deployment_key,
        "tenant_key": row.tenant_key,
        "deployment_id": row.deployment_id,
        "fingerprint": row.fingerprint,
        "environment": row.environment,
        "hostname": row.hostname,
        "site": row.site,
        "version": row.version,
        "image_digest": row.image_digest,
        "status": row.status,
        "license_key": row.license_key,
        "metadata": row.metadata_json,
        "registered_by": row.registered_by,
        "registered_at": iso(row.registered_at),
        "last_seen_at": iso(row.last_seen_at),
    }


def release_view(row: ReleaseManifest) -> dict[str, Any]:
    return {
        "key": row.release_key,
        "version": row.version,
        "channel": row.channel,
        "status": row.status,
        "image_ref": row.image_ref,
        "image_digest": row.image_digest,
        "signature_ref": row.signature_ref,
        "sbom_ref": row.sbom_ref,
        "provenance_ref": row.provenance_ref,
        "minimum_plan": row.minimum_plan,
        "notes": row.notes,
        "metadata": row.metadata_json,
        "created_at": iso(row.created_at),
        "published_at": iso(row.published_at),
    }
