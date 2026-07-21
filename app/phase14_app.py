from __future__ import annotations

import re
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import governance_service
import phase13_bootstrap  # noqa: F401 — install Phase 1–13 executive runtime
from business_models import TenantSubscription
from collaboration_models import CollaborationTask
from commercial_models import (
    BrandProfile,
    BrandUpdate,
    CommercialLicense,
    DeploymentActivation,
    DeploymentHeartbeat,
    DeploymentRegister,
    FeatureEntitlement,
    LicenseImport,
    OnboardingAdvance,
    OnboardingCreate,
    ReleaseManifest,
    TenantOnboarding,
    brand_view,
    deployment_view,
    entitlement_view,
    license_view,
    onboarding_view,
    release_view,
)
from commercial_service import (
    DEPLOYMENT_ID,
    LICENSE_MODE,
    ONBOARDING_STEPS,
    activate_license,
    commercial_status,
    current_license,
    entitlement_allowed,
    entitlement_limit,
    license_state,
    seed_commercial,
)
from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT, scoped_keys
from governance_models import GovernanceIdentity, GovernanceRole
from main import SessionLocal, app, db_session, utcnow
from phase6_app import require_governance
from phase12_app import tenant_header
from registry_models import RegisteredAgent

app.version = "0.15.0"

_PHASE14_RULES = [
    ("POST", re.compile(r"^/api/commercial/onboarding$"), "commercial:onboarding:manage"),
    ("POST", re.compile(r"^/api/commercial/onboarding/[^/]+/advance$"), "commercial:onboarding:manage"),
    ("POST", re.compile(r"^/api/commercial/license/import$"), "commercial:license:manage"),
    ("POST", re.compile(r"^/api/commercial/license/verify$"), "commercial:license:manage"),
    ("PUT", re.compile(r"^/api/commercial/brand$"), "commercial:brand:manage"),
    ("POST", re.compile(r"^/api/commercial/deployments$"), "commercial:deployment:manage"),
    ("POST", re.compile(r"^/api/commercial/deployments/[^/]+/heartbeat$"), "commercial:deployment:manage"),
]
for rule in reversed(_PHASE14_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.update(
    {
        "commercial:license:manage",
        "commercial:deployment:manage",
        "commercial:brand:manage",
    }
)


def ensure_commercial_permissions(db: Session) -> None:
    additions = {
        "role:executive": {
            "commercial:read",
            "commercial:onboarding:manage",
            "commercial:license:manage",
            "commercial:brand:manage",
            "commercial:deployment:manage",
            "commercial:release:read",
        },
        "role:manager": {
            "commercial:read",
            "commercial:onboarding:manage",
            "commercial:brand:manage",
            "commercial:deployment:manage",
            "commercial:release:read",
        },
        "role:operator": {
            "commercial:read",
            "commercial:deployment:manage",
            "commercial:release:read",
        },
        "role:auditor": {"commercial:read", "commercial:release:read"},
        "role:service": {
            "commercial:read",
            "commercial:deployment:manage",
            "commercial:release:read",
        },
        "role:agent": {"commercial:read"},
        "role:runtime": {"commercial:read"},
    }
    changed = False
    for role_key, permissions in additions.items():
        role = db.scalar(select(GovernanceRole).where(GovernanceRole.role_key == role_key))
        if role is None:
            continue
        merged = sorted(set(role.permissions or []) | permissions)
        if merged != role.permissions:
            role.permissions = merged
            role.updated_at = utcnow()
            changed = True
    if changed:
        db.commit()


@app.on_event("startup")
def start_commercial_layer() -> None:
    with SessionLocal() as db:
        ensure_commercial_permissions(db)
        seed_commercial(db)


_FEATURE_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/api/missions$"), "core.missions"),
    ("POST", re.compile(r"^/api/collaboration/"), "collaboration"),
    ("POST", re.compile(r"^/api/missions/[^/]+/meetings"), "meetings"),
    ("POST", re.compile(r"^/api/registry/agents"), "registry"),
    ("POST", re.compile(r"^/api/scheduler/"), "scheduler"),
    ("POST", re.compile(r"^/api/evaluation/"), "evaluation"),
    ("POST", re.compile(r"^/api/sop/"), "sop"),
    ("POST", re.compile(r"^/(message:send|mcp|v1/chat/completions|hooks/)"), "protocol"),
    ("POST", re.compile(r"^/api/runtimes/[^/]+/dispatch$"), "runtime.dispatch"),
    ("POST", re.compile(r"^/api/runtime-dispatches/"), "runtime.dispatch"),
    ("POST", re.compile(r"^/api/enterprise/backup/"), "backup_dr"),
    ("POST", re.compile(r"^/api/enterprise/siem/"), "siem"),
    ("POST", re.compile(r"^/api/business/industry-packs/"), "marketplace"),
    ("POST", re.compile(r"^/api/business/"), "business"),
]


def feature_for_request(method: str, path: str) -> str | None:
    normalized = method.upper()
    for expected_method, pattern, feature in _FEATURE_ROUTES:
        if normalized == expected_method and pattern.match(path):
            return feature
    return None


def active_task_count(db: Session, tenant_key: str) -> int:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    if not mission_keys:
        return 0
    return int(
        db.scalar(
            select(func.count(CollaborationTask.id)).where(
                CollaborationTask.mission_key.in_(mission_keys),
                CollaborationTask.status.in_(
                    ["QUEUED", "DISPATCHING", "RUNNING", "WAITING", "BLOCKED", "REVIEW"]
                ),
            )
        )
        or 0
    )


@app.middleware("http")
async def commercial_license_enforcement(request: Request, call_next: Callable):
    path = request.url.path
    feature = feature_for_request(request.method, path)
    if feature is None or path.startswith("/api/commercial/"):
        return await call_next(request)
    tenant_key = request.headers.get("X-Beeza-Tenant", DEFAULT_TENANT)
    with SessionLocal() as db:
        state = license_state(db, tenant_key)
        if not state["allowed"]:
            return JSONResponse(
                status_code=402,
                content={
                    "detail": "A valid BeezaOffice commercial license is required",
                    "tenant_key": tenant_key,
                    "deployment_id": DEPLOYMENT_ID,
                    "license_mode": LICENSE_MODE,
                },
            )
        if state["valid"] and not entitlement_allowed(db, tenant_key, feature):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Feature entitlement {feature} is not enabled",
                    "tenant_key": tenant_key,
                },
            )
        if request.method.upper() == "POST" and path == "/api/registry/agents":
            limit = entitlement_limit(db, tenant_key, "max_agents", 0)
            count = int(
                db.scalar(
                    select(func.count(RegisteredAgent.id))
                    .join(
                        GovernanceIdentity,
                        GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
                    )
                    .where(GovernanceIdentity.tenant_key == tenant_key)
                )
                or 0
            )
            if limit and count >= limit:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Licensed agent limit reached", "limit": limit},
                )
        if request.method.upper() == "POST" and feature in {
            "collaboration",
            "meetings",
            "sop",
            "protocol",
            "runtime.dispatch",
        }:
            limit = entitlement_limit(db, tenant_key, "max_concurrent_tasks", 0)
            count = active_task_count(db, tenant_key)
            if limit and count >= limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Licensed concurrent-task limit reached",
                        "limit": limit,
                        "active": count,
                    },
                )
    response = await call_next(request)
    response.headers["X-Beeza-License-Mode"] = LICENSE_MODE
    response.headers["X-Beeza-Deployment"] = DEPLOYMENT_ID
    if not state["valid"]:
        response.headers["X-Beeza-License-Warning"] = "unverified"
    return response


@app.get("/api/commercial/status")
def read_commercial_status(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return commercial_status(db, tenant_key)


@app.get("/api/commercial/onboarding")
def read_onboarding(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any] | None:
    row = db.scalar(
        select(TenantOnboarding).where(TenantOnboarding.tenant_key == tenant_key)
    )
    return onboarding_view(row) if row else None


@app.post("/api/commercial/onboarding")
def upsert_onboarding(
    payload: OnboardingCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("commercial:onboarding:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    tenant = db.scalar(
        select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == tenant_key)
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    now = utcnow()
    row = db.scalar(
        select(TenantOnboarding).where(TenantOnboarding.tenant_key == tenant_key)
    )
    if row is None:
        row = TenantOnboarding(
            onboarding_key=f"ONB-{uuid4().hex[:14].upper()}",
            tenant_key=tenant_key,
            organization_name=payload.organization_name,
            primary_contact=payload.primary_contact,
            requested_plan=payload.requested_plan,
            deployment_mode=payload.deployment_mode,
            desired_domain=payload.desired_domain,
            data_region=payload.data_region,
            status="IN_PROGRESS",
            current_step=ONBOARDING_STEPS[0],
            checklist={step: False for step in ONBOARDING_STEPS},
            settings=payload.settings,
            created_by=actor,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        db.add(row)
    else:
        row.organization_name = payload.organization_name
        row.primary_contact = payload.primary_contact
        row.requested_plan = payload.requested_plan
        row.deployment_mode = payload.deployment_mode
        row.desired_domain = payload.desired_domain
        row.data_region = payload.data_region
        row.settings = payload.settings
        if row.status in {"DRAFT", "CANCELLED"}:
            row.status = "IN_PROGRESS"
        row.updated_at = now
    tenant.name = payload.organization_name
    tenant.data_region = payload.data_region
    db.commit()
    db.refresh(row)
    return onboarding_view(row)


@app.post("/api/commercial/onboarding/{onboarding_key}/advance")
def advance_onboarding(
    onboarding_key: str,
    payload: OnboardingAdvance,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("commercial:onboarding:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(TenantOnboarding).where(
            TenantOnboarding.onboarding_key == onboarding_key,
            TenantOnboarding.tenant_key == tenant_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Onboarding record not found")
    if payload.step not in ONBOARDING_STEPS:
        raise HTTPException(status_code=422, detail="Unknown onboarding step")
    checklist = dict(row.checklist or {})
    checklist[payload.step] = payload.completed
    if payload.note:
        notes = dict(row.settings or {}).get("step_notes", {})
        notes[payload.step] = {"note": payload.note, "actor": actor, "at": utcnow().isoformat()}
        row.settings = {**(row.settings or {}), "step_notes": notes}
    row.checklist = checklist
    missing = [step for step in ONBOARDING_STEPS if not checklist.get(step)]
    row.current_step = missing[0] if missing else "go_live"
    row.status = "IN_PROGRESS" if missing else "COMPLETED"
    row.completed_at = None if missing else utcnow()
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return onboarding_view(row)


@app.get("/api/commercial/license")
def read_license(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return license_state(db, tenant_key)


@app.post("/api/commercial/license/import")
def import_license(
    payload: LicenseImport,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("commercial:license:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    try:
        row = activate_license(db, tenant_key, payload.token, actor)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)[:1000]) from exc
    return license_view(row)


@app.post("/api/commercial/license/verify")
def verify_current_license(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:license:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = current_license(db, tenant_key)
    db.commit()
    return {
        **license_state(db, tenant_key),
        "verified_at": utcnow().isoformat(),
        "verification_type": "stored-claims-expiry-and-deployment-check",
        "requires_reimport_for_signature_reverification": True,
        "license_key": row.license_key if row else None,
    }


@app.get("/api/commercial/entitlements")
def list_entitlements(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(FeatureEntitlement)
        .where(FeatureEntitlement.tenant_key == tenant_key)
        .order_by(FeatureEntitlement.feature_key)
    ).all()
    return [entitlement_view(row) for row in rows]


@app.get("/api/commercial/brand")
def read_brand(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(select(BrandProfile).where(BrandProfile.tenant_key == tenant_key))
    if row is None:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return brand_view(row)


@app.put("/api/commercial/brand")
def update_brand(
    payload: BrandUpdate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("commercial:brand:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if LICENSE_MODE == "enforce" and not entitlement_allowed(db, tenant_key, "white_label"):
        raise HTTPException(status_code=403, detail="White-label entitlement is required")
    row = db.scalar(select(BrandProfile).where(BrandProfile.tenant_key == tenant_key))
    if row is None:
        row = BrandProfile(
            tenant_key=tenant_key,
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
            settings={},
            updated_by=actor,
            updated_at=utcnow(),
        )
        db.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by = actor
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return brand_view(row)


@app.get("/api/commercial/deployments")
def list_deployments(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DeploymentActivation)
        .where(DeploymentActivation.tenant_key == tenant_key)
        .order_by(DeploymentActivation.registered_at.desc())
    ).all()
    return [deployment_view(row) for row in rows]


@app.post("/api/commercial/deployments", status_code=201)
def register_deployment(
    payload: DeploymentRegister,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("commercial:deployment:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    limit = entitlement_limit(db, tenant_key, "max_deployments", 0)
    count = int(
        db.scalar(
            select(func.count(DeploymentActivation.id)).where(
                DeploymentActivation.tenant_key == tenant_key,
                DeploymentActivation.status != "REVOKED",
            )
        )
        or 0
    )
    existing = db.scalar(
        select(DeploymentActivation).where(
            DeploymentActivation.deployment_id == payload.deployment_id
        )
    )
    if existing is None and limit and count >= limit:
        raise HTTPException(status_code=409, detail="Licensed deployment limit reached")
    if existing and existing.tenant_key != tenant_key:
        raise HTTPException(status_code=409, detail="Deployment ID belongs to another tenant")
    now = utcnow()
    license_row = current_license(db, tenant_key)
    if existing is None:
        existing = DeploymentActivation(
            deployment_key=f"DEP-{uuid4().hex[:14].upper()}",
            tenant_key=tenant_key,
            deployment_id=payload.deployment_id,
            fingerprint=payload.fingerprint,
            environment=payload.environment,
            hostname=payload.hostname,
            site=payload.site,
            version=payload.version,
            image_digest=payload.image_digest,
            status="ACTIVE" if license_row else "REGISTERED",
            license_key=license_row.license_key if license_row else None,
            metadata_json=payload.metadata,
            registered_by=actor,
            registered_at=now,
            last_seen_at=now,
        )
        db.add(existing)
    else:
        existing.fingerprint = payload.fingerprint
        existing.environment = payload.environment
        existing.hostname = payload.hostname
        existing.site = payload.site
        existing.version = payload.version
        existing.image_digest = payload.image_digest
        existing.metadata_json = payload.metadata
        existing.status = "ACTIVE" if license_row else "REGISTERED"
        existing.license_key = license_row.license_key if license_row else None
        existing.last_seen_at = now
    db.commit()
    db.refresh(existing)
    return deployment_view(existing)


@app.post("/api/commercial/deployments/{deployment_key}/heartbeat")
def deployment_heartbeat(
    deployment_key: str,
    payload: DeploymentHeartbeat,
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:deployment:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(DeploymentActivation).where(
            DeploymentActivation.deployment_key == deployment_key,
            DeploymentActivation.tenant_key == tenant_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    row.status = payload.status
    if payload.version is not None:
        row.version = payload.version
    if payload.image_digest is not None:
        row.image_digest = payload.image_digest
    row.metadata_json = {**(row.metadata_json or {}), **payload.metadata}
    row.last_seen_at = utcnow()
    db.commit()
    db.refresh(row)
    return deployment_view(row)


@app.get("/api/commercial/releases")
def list_releases(
    channel: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=500),
    _: str = Depends(require_governance("commercial:release:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(ReleaseManifest)
    if channel:
        statement = statement.where(ReleaseManifest.channel == channel)
    rows = db.scalars(
        statement.order_by(ReleaseManifest.created_at.desc()).limit(limit)
    ).all()
    return [release_view(row) for row in rows]


@app.get("/api/commercial/installer-config")
def installer_config(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("commercial:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    release = db.scalar(
        select(ReleaseManifest)
        .where(ReleaseManifest.channel == "stable")
        .order_by(ReleaseManifest.created_at.desc())
    )
    subscription = db.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_key == tenant_key)
    )
    return {
        "tenant_key": tenant_key,
        "deployment_id": DEPLOYMENT_ID,
        "license_mode": LICENSE_MODE,
        "plan_key": subscription.plan_key if subscription else None,
        "release": release_view(release) if release else None,
        "required_secrets": [
            "POSTGRES_PASSWORD",
            "BEEZA_AUTH_TOKEN",
            "BEEZA_METRICS_TOKEN",
        ],
        "required_license_settings": [
            "BEEZA_LICENSE_MODE=enforce",
            "BEEZA_DEPLOYMENT_ID",
            "BEEZA_LICENSE_PUBLIC_KEY",
            "BEEZA_LICENSE_TOKEN",
        ],
        "install_script": "deploy/install/install.sh",
        "verification": [
            "GET /health/live",
            "GET /health/ready",
            "GET /api/commercial/status",
            "Verify image signature and digest before deployment",
        ],
    }
