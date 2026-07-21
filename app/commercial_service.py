from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from business_models import BillingPlan, TenantSubscription
from commercial_models import (
    BrandProfile,
    CommercialLicense,
    DeploymentActivation,
    FeatureEntitlement,
    ReleaseManifest,
    TenantOnboarding,
    brand_view,
    deployment_view,
    entitlement_view,
    license_view,
    onboarding_view,
    release_view,
)
from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT
from main import utcnow

LICENSE_MODE = os.getenv("BEEZA_LICENSE_MODE", "development").strip().lower()
LICENSE_PUBLIC_KEY = os.getenv("BEEZA_LICENSE_PUBLIC_KEY", "").replace("\\n", "\n").strip()
LICENSE_ISSUER = os.getenv("BEEZA_LICENSE_ISSUER", "beezaoffice-license").strip()
LICENSE_AUDIENCE = os.getenv("BEEZA_LICENSE_AUDIENCE", "beezaoffice").strip()
LICENSE_ALGORITHMS = [
    item.strip()
    for item in os.getenv("BEEZA_LICENSE_ALGORITHMS", "EdDSA,RS256,ES256").split(",")
    if item.strip()
]
DEPLOYMENT_ID = os.getenv("BEEZA_DEPLOYMENT_ID", "deployment:local").strip()
LICENSE_TOKEN = os.getenv("BEEZA_LICENSE_TOKEN", "").strip()
RELEASE_IMAGE = os.getenv(
    "BEEZA_RELEASE_IMAGE", "ghcr.io/paddman/beezaoffice:0.15.0"
).strip()

ALL_FEATURES = [
    "core.missions",
    "collaboration",
    "meetings",
    "governance",
    "registry",
    "scheduler",
    "evaluation",
    "sop",
    "protocol",
    "runtime.dispatch",
    "enterprise",
    "business",
    "marketplace",
    "white_label",
    "backup_dr",
    "siem",
    "metrics",
    "kubernetes",
]

PLAN_FEATURES: dict[str, list[str]] = {
    "plan:team": [
        "core.missions",
        "collaboration",
        "meetings",
        "governance",
        "registry",
        "scheduler",
        "evaluation",
        "sop",
        "protocol",
        "runtime.dispatch",
        "business",
        "metrics",
    ],
    "plan:enterprise": [
        "core.missions",
        "collaboration",
        "meetings",
        "governance",
        "registry",
        "scheduler",
        "evaluation",
        "sop",
        "protocol",
        "runtime.dispatch",
        "enterprise",
        "business",
        "marketplace",
        "white_label",
        "backup_dr",
        "siem",
        "metrics",
        "kubernetes",
    ],
    "plan:sovereign": ALL_FEATURES,
}

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "plan:team": {
        "max_agents": 50,
        "max_concurrent_tasks": 20,
        "max_tenants": 1,
        "max_deployments": 1,
    },
    "plan:enterprise": {
        "max_agents": 500,
        "max_concurrent_tasks": 100,
        "max_tenants": 10,
        "max_deployments": 4,
    },
    "plan:sovereign": {
        "max_agents": 1000,
        "max_concurrent_tasks": 200,
        "max_tenants": 50,
        "max_deployments": 20,
    },
}

ONBOARDING_STEPS = [
    "organization",
    "deployment",
    "identity",
    "runtime",
    "governance",
    "backup",
    "verification",
    "go_live",
]


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError("Unsupported license timestamp")


def active_now(valid_from: datetime | None, valid_until: datetime | None) -> bool:
    now = utcnow()
    return (valid_from is None or valid_from <= now) and (
        valid_until is None or valid_until > now
    )


def verify_license_token(encoded: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not LICENSE_PUBLIC_KEY:
        raise ValueError("BEEZA_LICENSE_PUBLIC_KEY is not configured")
    header = jwt.get_unverified_header(encoded)
    algorithm = str(header.get("alg") or "")
    if algorithm not in LICENSE_ALGORITHMS:
        raise ValueError(f"License algorithm {algorithm or 'missing'} is not allowed")
    claims = jwt.decode(
        encoded,
        LICENSE_PUBLIC_KEY,
        algorithms=LICENSE_ALGORITHMS,
        audience=LICENSE_AUDIENCE,
        issuer=LICENSE_ISSUER,
        options={"require": ["exp", "iat", "jti", "tenant_key", "deployment_id"]},
    )
    if claims.get("deployment_id") != DEPLOYMENT_ID:
        raise ValueError("License is bound to a different deployment")
    return header, claims


def set_entitlements(
    db: Session,
    tenant_key: str,
    source: str,
    source_key: str,
    features: list[str],
    limits: dict[str, int],
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> None:
    now = utcnow()
    current = {
        row.feature_key: row
        for row in db.scalars(
            select(FeatureEntitlement).where(
                FeatureEntitlement.tenant_key == tenant_key,
                FeatureEntitlement.source == source,
            )
        ).all()
    }
    desired: dict[str, int | None] = {feature: None for feature in features}
    desired.update({f"limit.{key}": int(value) for key, value in limits.items()})
    for feature_key, limit_value in desired.items():
        row = current.pop(feature_key, None)
        if row is None:
            row = FeatureEntitlement(
                entitlement_key=f"ENT-{uuid4().hex[:16].upper()}",
                tenant_key=tenant_key,
                feature_key=feature_key,
                enabled=True,
                limit_value=limit_value,
                source=source,
                source_key=source_key,
                valid_from=valid_from,
                valid_until=valid_until,
                metadata_json={},
                updated_at=now,
            )
            db.add(row)
        else:
            row.enabled = True
            row.limit_value = limit_value
            row.source_key = source_key
            row.valid_from = valid_from
            row.valid_until = valid_until
            row.updated_at = now
    for row in current.values():
        row.enabled = False
        row.updated_at = now


def activate_license(
    db: Session,
    tenant_key: str,
    encoded: str,
    actor: str,
) -> CommercialLicense:
    header, claims = verify_license_token(encoded)
    if claims.get("tenant_key") != tenant_key:
        raise ValueError("License belongs to a different tenant")
    plan_key = str(claims.get("plan_key") or "plan:enterprise")
    features = sorted(
        set(str(item) for item in (claims.get("features") or PLAN_FEATURES.get(plan_key, [])))
    )
    limits = {
        str(key): int(value)
        for key, value in (claims.get("limits") or PLAN_LIMITS.get(plan_key, {})).items()
    }
    not_before = as_datetime(claims.get("nbf"))
    expires_at = as_datetime(claims.get("exp"))
    now = utcnow()
    digest = token_hash(encoded)
    existing = db.scalar(
        select(CommercialLicense).where(CommercialLicense.token_hash == digest)
    )
    if existing is not None:
        existing.last_verified_at = now
        existing.status = "ACTIVE"
        existing.verification_error = None
        set_entitlements(
            db,
            tenant_key,
            "LICENSE",
            existing.license_key,
            features,
            limits,
            not_before,
            expires_at,
        )
        db.commit()
        db.refresh(existing)
        return existing

    for row in db.scalars(
        select(CommercialLicense).where(
            CommercialLicense.tenant_key == tenant_key,
            CommercialLicense.deployment_id == DEPLOYMENT_ID,
            CommercialLicense.status.in_(["ACTIVE", "DEVELOPMENT"]),
        )
    ).all():
        row.status = "REVOKED"

    row = CommercialLicense(
        license_key=str(claims.get("jti")),
        tenant_key=tenant_key,
        deployment_id=str(claims.get("deployment_id")),
        plan_key=plan_key,
        status="ACTIVE",
        token_hash=digest,
        issuer=str(claims.get("iss") or LICENSE_ISSUER),
        subject=str(claims.get("sub") or tenant_key),
        signature_algorithm=str(header.get("alg") or ""),
        features=features,
        limits=limits,
        claims={
            key: value
            for key, value in claims.items()
            if key not in {"customer_secret", "private_key"}
        },
        not_before=not_before,
        expires_at=expires_at,
        activated_by=actor,
        activated_at=now,
        last_verified_at=now,
        verification_error=None,
    )
    db.add(row)
    set_entitlements(
        db,
        tenant_key,
        "LICENSE",
        row.license_key,
        features,
        limits,
        not_before,
        expires_at,
    )
    deployment = db.scalar(
        select(DeploymentActivation).where(
            DeploymentActivation.deployment_id == DEPLOYMENT_ID,
            DeploymentActivation.tenant_key == tenant_key,
        )
    )
    if deployment:
        deployment.license_key = row.license_key
        deployment.status = "ACTIVE"
        deployment.last_seen_at = now
    db.commit()
    db.refresh(row)
    return row


def current_license(db: Session, tenant_key: str) -> CommercialLicense | None:
    rows = list(
        db.scalars(
            select(CommercialLicense)
            .where(CommercialLicense.tenant_key == tenant_key)
            .order_by(CommercialLicense.activated_at.desc())
        ).all()
    )
    now = utcnow()
    for row in rows:
        if row.status not in {"ACTIVE", "DEVELOPMENT"}:
            continue
        if row.not_before and row.not_before > now:
            row.status = "INVALID"
            row.verification_error = "License is not active yet"
            continue
        if row.expires_at and row.expires_at <= now:
            row.status = "EXPIRED"
            row.verification_error = "License has expired"
            continue
        return row
    return None


def effective_entitlements(db: Session, tenant_key: str) -> list[FeatureEntitlement]:
    rows = list(
        db.scalars(
            select(FeatureEntitlement)
            .where(
                FeatureEntitlement.tenant_key == tenant_key,
                FeatureEntitlement.enabled.is_(True),
            )
            .order_by(FeatureEntitlement.feature_key)
        ).all()
    )
    return [row for row in rows if active_now(row.valid_from, row.valid_until)]


def entitlement_map(db: Session, tenant_key: str) -> dict[str, int | bool | None]:
    result: dict[str, int | bool | None] = {}
    for row in effective_entitlements(db, tenant_key):
        result[row.feature_key] = row.limit_value if row.feature_key.startswith("limit.") else True
    return result


def entitlement_allowed(db: Session, tenant_key: str, feature_key: str) -> bool:
    return bool(entitlement_map(db, tenant_key).get(feature_key))


def entitlement_limit(
    db: Session,
    tenant_key: str,
    limit_key: str,
    default: int = 0,
) -> int:
    value = entitlement_map(db, tenant_key).get(f"limit.{limit_key}")
    return int(value) if isinstance(value, int) else default


def license_state(db: Session, tenant_key: str) -> dict[str, Any]:
    row = current_license(db, tenant_key)
    entitlements = effective_entitlements(db, tenant_key)
    valid = row is not None
    allowed = valid or LICENSE_MODE in {"development", "warn"}
    return {
        "mode": LICENSE_MODE,
        "valid": valid,
        "allowed": allowed,
        "deployment_id": DEPLOYMENT_ID,
        "license": license_view(row) if row else None,
        "features": [
            item.feature_key
            for item in entitlements
            if not item.feature_key.startswith("limit.")
        ],
        "limits": {
            item.feature_key.removeprefix("limit."): item.limit_value
            for item in entitlements
            if item.feature_key.startswith("limit.")
        },
        "warning": None if valid else "No active verified commercial license",
    }


def default_fingerprint() -> str:
    raw = f"{DEPLOYMENT_ID}:{socket.gethostname()}"
    return token_hash(raw)[:40]


def seed_commercial(db: Session) -> None:
    now = utcnow()
    tenant = db.scalar(
        select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == DEFAULT_TENANT)
    )
    if tenant is None:
        return

    brand = db.scalar(
        select(BrandProfile).where(BrandProfile.tenant_key == DEFAULT_TENANT)
    )
    if brand is None:
        db.add(
            BrandProfile(
                tenant_key=DEFAULT_TENANT,
                product_name="BeezaOffice",
                company_name="BeezaOffice",
                logo_url="",
                favicon_url="",
                primary_color="#dc285c",
                accent_color="#1677ff",
                background_color="#ffffff",
                support_url="",
                privacy_url="",
                terms_url="",
                custom_domain="",
                locale="en",
                email_from="",
                settings={"white_label": False},
                updated_by="system:phase14",
                updated_at=now,
            )
        )

    onboarding = db.scalar(
        select(TenantOnboarding).where(TenantOnboarding.tenant_key == DEFAULT_TENANT)
    )
    if onboarding is None:
        db.add(
            TenantOnboarding(
                onboarding_key=f"ONB-{uuid4().hex[:14].upper()}",
                tenant_key=DEFAULT_TENANT,
                organization_name=tenant.name,
                primary_contact="",
                requested_plan="plan:sovereign",
                deployment_mode="SOVEREIGN",
                desired_domain="",
                data_region=tenant.data_region,
                status="COMPLETED",
                current_step="go_live",
                checklist={step: True for step in ONBOARDING_STEPS},
                settings={"seeded": True},
                created_by="system:phase14",
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )

    deployment = db.scalar(
        select(DeploymentActivation).where(
            DeploymentActivation.deployment_id == DEPLOYMENT_ID
        )
    )
    if deployment is None:
        db.add(
            DeploymentActivation(
                deployment_key=f"DEP-{uuid4().hex[:14].upper()}",
                tenant_key=DEFAULT_TENANT,
                deployment_id=DEPLOYMENT_ID,
                fingerprint=default_fingerprint(),
                environment="development" if LICENSE_MODE == "development" else "production",
                hostname=socket.gethostname(),
                site="primary",
                version="0.15.0",
                image_digest="",
                status="ACTIVE" if LICENSE_MODE == "development" else "REGISTERED",
                license_key=None,
                metadata_json={"seeded": True},
                registered_by="system:phase14",
                registered_at=now,
                last_seen_at=now,
            )
        )

    release = db.scalar(
        select(ReleaseManifest).where(
            ReleaseManifest.version == "0.15.0",
            ReleaseManifest.channel == "stable",
        )
    )
    if release is None:
        db.add(
            ReleaseManifest(
                release_key="REL-0.15.0-STABLE",
                version="0.15.0",
                channel="stable",
                status="UNSIGNED",
                image_ref=RELEASE_IMAGE,
                image_digest="",
                signature_ref="",
                sbom_ref="",
                provenance_ref="",
                minimum_plan="plan:team",
                notes="Phase 14 commercial productization baseline. Tag workflow publishes signed artifacts.",
                metadata_json={"phase": 14},
                created_at=now,
                published_at=None,
            )
        )

    db.flush()
    if LICENSE_MODE == "development":
        dev = db.scalar(
            select(CommercialLicense).where(
                CommercialLicense.tenant_key == DEFAULT_TENANT,
                CommercialLicense.deployment_id == DEPLOYMENT_ID,
                CommercialLicense.status == "DEVELOPMENT",
            )
        )
        if dev is None:
            dev = CommercialLicense(
                license_key=f"LIC-DEV-{token_hash(DEFAULT_TENANT + DEPLOYMENT_ID)[:12].upper()}",
                tenant_key=DEFAULT_TENANT,
                deployment_id=DEPLOYMENT_ID,
                plan_key="plan:sovereign",
                status="DEVELOPMENT",
                token_hash=token_hash(f"development:{DEFAULT_TENANT}:{DEPLOYMENT_ID}"),
                issuer="local-development",
                subject=DEFAULT_TENANT,
                signature_algorithm="NONE-DEVELOPMENT",
                features=ALL_FEATURES,
                limits=PLAN_LIMITS["plan:sovereign"],
                claims={"development": True},
                not_before=now,
                expires_at=None,
                activated_by="system:phase14",
                activated_at=now,
                last_verified_at=now,
                verification_error=None,
            )
            db.add(dev)
        set_entitlements(
            db,
            DEFAULT_TENANT,
            "DEVELOPMENT",
            dev.license_key,
            ALL_FEATURES,
            PLAN_LIMITS["plan:sovereign"],
            now,
            None,
        )
    db.commit()

    if LICENSE_TOKEN and LICENSE_MODE != "development":
        existing = db.scalar(
            select(CommercialLicense).where(
                CommercialLicense.token_hash == token_hash(LICENSE_TOKEN)
            )
        )
        if existing is None:
            activate_license(db, DEFAULT_TENANT, LICENSE_TOKEN, "system:phase14")


def commercial_status(db: Session, tenant_key: str) -> dict[str, Any]:
    onboarding = db.scalar(
        select(TenantOnboarding).where(TenantOnboarding.tenant_key == tenant_key)
    )
    brand = db.scalar(select(BrandProfile).where(BrandProfile.tenant_key == tenant_key))
    deployments = list(
        db.scalars(
            select(DeploymentActivation)
            .where(DeploymentActivation.tenant_key == tenant_key)
            .order_by(DeploymentActivation.registered_at.desc())
        ).all()
    )
    subscription = db.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_key == tenant_key)
    )
    plan = (
        db.scalar(select(BillingPlan).where(BillingPlan.plan_key == subscription.plan_key))
        if subscription
        else None
    )
    license_info = license_state(db, tenant_key)
    return {
        "version": "0.15.0",
        "tenant_key": tenant_key,
        "onboarding": onboarding_view(onboarding) if onboarding else None,
        "brand": brand_view(brand) if brand else None,
        "license": license_info,
        "subscription": {
            "plan_key": subscription.plan_key,
            "status": subscription.status,
            "plan_name": plan.name if plan else subscription.plan_key,
        }
        if subscription
        else None,
        "deployments": [deployment_view(row) for row in deployments],
        "release": release_view(
            db.scalar(
                select(ReleaseManifest)
                .where(ReleaseManifest.channel == "stable")
                .order_by(ReleaseManifest.created_at.desc())
            )
        )
        if db.scalar(select(ReleaseManifest.id).limit(1))
        else None,
        "production_ready": bool(
            onboarding
            and onboarding.status == "COMPLETED"
            and license_info["valid"]
            and deployments
            and any(row.status == "ACTIVE" for row in deployments)
        ),
    }
