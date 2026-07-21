from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase11_bootstrap  # noqa: F401 — install Phase 1–11 and protocol hardening
from enterprise_models import (
    ApiKeyCreate,
    BackupPlan,
    BackupPlanCreate,
    BackupRun,
    BackupRunComplete,
    DeploymentSite,
    EnterpriseApiKey,
    EnterpriseTenant,
    IdentityProvider,
    IdentityProviderCreate,
    OIDCExchange,
    ResourceScope,
    SIEMSink,
    SIEMSinkCreate,
    TenantCreate,
)
from enterprise_service import (
    API_KEY_PREFIX,
    DEFAULT_TENANT,
    api_key_view,
    audit_export,
    backup_manifest,
    backup_plan_view,
    backup_run_view,
    discover_oidc,
    enterprise_status,
    idp_view,
    issue_session,
    provision_membership,
    random_token,
    scope_resource,
    seed_enterprise,
    siem_view,
    site_view,
    tenant_view,
    token_hash,
    verify_oidc_token,
)
from governance_models import GovernanceIdentity, GovernanceRole, RoleBinding, Tenant
from main import SessionLocal, app, db_session, redis_client, utcnow
from phase6_app import require_governance

app.version = "0.13.0"

_PHASE12_RULES = [
    ("POST", re.compile(r"^/api/enterprise/tenants$"), "enterprise:tenant:manage"),
    ("POST", re.compile(r"^/api/enterprise/identity-providers$"), "enterprise:sso:manage"),
    ("POST", re.compile(r"^/api/enterprise/identity-providers/[^/]+/discover$"), "enterprise:sso:manage"),
    ("POST", re.compile(r"^/api/enterprise/api-keys$"), "enterprise:credentials:manage"),
    ("DELETE", re.compile(r"^/api/enterprise/api-keys/[^/]+$"), "enterprise:credentials:manage"),
    ("POST", re.compile(r"^/api/enterprise/backup/plans$"), "enterprise:backup:manage"),
    ("POST", re.compile(r"^/api/enterprise/backup/plans/[^/]+/runs$"), "enterprise:backup:run"),
    ("POST", re.compile(r"^/api/enterprise/backup/runs/[^/]+/complete$"), "enterprise:backup:complete"),
    ("POST", re.compile(r"^/api/enterprise/siem/sinks$"), "enterprise:siem:manage"),
    ("POST", re.compile(r"^/api/enterprise/siem/sinks/[^/]+/checkpoint$"), "enterprise:siem:operate"),
]
for rule in reversed(_PHASE12_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.update({"enterprise:backup:run", "enterprise:backup:complete"})


def ensure_enterprise_permissions(db: Session) -> None:
    additions = {
        "role:executive": {
            "enterprise:read", "enterprise:tenant:manage", "enterprise:sso:manage",
            "enterprise:credentials:manage", "enterprise:backup:manage",
            "enterprise:backup:run", "enterprise:backup:complete",
            "enterprise:siem:manage", "enterprise:siem:operate",
        },
        "role:manager": {"enterprise:read", "enterprise:backup:run", "enterprise:siem:operate"},
        "role:operator": {"enterprise:read", "enterprise:backup:run", "enterprise:siem:operate"},
        "role:auditor": {"enterprise:read", "enterprise:siem:operate"},
        "role:service": {"enterprise:read", "enterprise:backup:complete", "enterprise:siem:operate"},
        "role:agent": {"enterprise:read"},
        "role:runtime": {"enterprise:read"},
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


def seed_enterprise_identity(db: Session) -> None:
    now = utcnow()
    identity_key = "service:enterprise"
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == identity_key)
    )
    if identity is None:
        db.add(
            GovernanceIdentity(
                identity_key=identity_key,
                tenant_key=DEFAULT_TENANT,
                identity_type="SERVICE",
                display_name="Beeza Enterprise Control Plane",
                department_key="dept:platform",
                status="ACTIVE",
                clearance="RESTRICTED",
                daily_budget_usd=5000.0,
                monthly_budget_usd=150000.0,
                attributes={
                    "seeded": True,
                    "purpose": "tenant isolation, SSO, API keys, backup, DR and SIEM export",
                },
                created_at=now,
                updated_at=now,
            )
        )
    binding = db.scalar(
        select(RoleBinding).where(
            RoleBinding.identity_key == identity_key,
            RoleBinding.role_key == "role:service",
            RoleBinding.scope_type == "GLOBAL",
            RoleBinding.scope_key == "*",
        )
    )
    if binding is None:
        db.add(
            RoleBinding(
                binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                identity_key=identity_key,
                role_key="role:service",
                scope_type="GLOBAL",
                scope_key="*",
                created_by="system:phase12",
                created_at=now,
            )
        )
    db.commit()


@app.on_event("startup")
def start_enterprise_platform() -> None:
    with SessionLocal() as db:
        ensure_enterprise_permissions(db)
        seed_enterprise_identity(db)
        seed_enterprise(db)
    redis_client.hset(
        "beezaoffice:enterprise",
        mapping={"status": "ready", "version": app.version, "started_at": utcnow().isoformat()},
    )


def tenant_header(
    x_beeza_tenant: str | None = Header(default=None, alias="X-Beeza-Tenant"),
) -> str:
    return (x_beeza_tenant or DEFAULT_TENANT).strip() or DEFAULT_TENANT


@app.get("/api/enterprise/status")
def read_enterprise_status(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return enterprise_status(db, tenant_key)


@app.get("/api/enterprise/tenants")
def list_enterprise_tenants(
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(EnterpriseTenant).order_by(EnterpriseTenant.display_name)).all()
    return [tenant_view(row) for row in rows]


@app.post("/api/enterprise/tenants", status_code=201)
def create_enterprise_tenant(
    payload: TenantCreate,
    actor: str = Depends(require_governance("enterprise:tenant:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    tenant_key = f"tenant:{payload.slug}"
    if db.scalar(select(EnterpriseTenant.id).where(EnterpriseTenant.tenant_key == tenant_key)):
        raise HTTPException(status_code=409, detail="Tenant already exists")
    now = utcnow()
    db.add(
        Tenant(
            tenant_key=tenant_key,
            name=payload.display_name,
            status="ACTIVE",
            data_region=payload.data_region,
            created_at=now,
            updated_at=now,
        )
    )
    row = EnterpriseTenant(
        tenant_key=tenant_key,
        slug=payload.slug,
        display_name=payload.display_name,
        status="ACTIVE",
        isolation_mode=payload.isolation_mode,
        data_region=payload.data_region,
        namespace=f"beeza-{payload.slug}",
        object_store_bucket=f"beeza-{payload.slug}-evidence",
        encryption_key_ref="",
        max_agents=payload.max_agents,
        max_concurrent_tasks=payload.max_concurrent_tasks,
        requests_per_minute=payload.requests_per_minute,
        retention_days=365,
        air_gapped=payload.air_gapped,
        settings={"created_by": actor},
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.add(
        DeploymentSite(
            site_key=f"site:{payload.slug}:primary",
            tenant_key=tenant_key,
            name=f"{payload.display_name} Primary",
            site_type="PRIMARY",
            region=payload.data_region,
            status="READY",
            rpo_minutes=15,
            rto_minutes=60,
            capabilities=["control-plane", "runtime-mesh"],
            last_heartbeat_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.refresh(row)
    return tenant_view(row)


@app.get("/api/enterprise/identity-providers")
def list_identity_providers(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(IdentityProvider)
        .where(IdentityProvider.tenant_key == tenant_key)
        .order_by(IdentityProvider.name)
    ).all()
    return [idp_view(row) for row in rows]


@app.post("/api/enterprise/identity-providers", status_code=201)
def create_identity_provider(
    payload: IdentityProviderCreate,
    actor: str = Depends(require_governance("enterprise:sso:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if db.scalar(select(EnterpriseTenant.id).where(EnterpriseTenant.tenant_key == payload.tenant_key)) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    key = f"idp:{payload.tenant_key.split(':')[-1]}:{uuid4().hex[:10]}"
    now = utcnow()
    row = IdentityProvider(
        provider_key=key,
        tenant_key=payload.tenant_key,
        name=payload.name,
        provider_type=payload.provider_type,
        issuer_url=payload.issuer_url.rstrip("/"),
        client_id=payload.client_id,
        audience=payload.audience,
        jwks_uri=payload.jwks_uri,
        authorization_endpoint="",
        token_endpoint="",
        allowed_algorithms=["RS256"],
        subject_claim="sub",
        email_claim="email",
        groups_claim="groups",
        role_map=payload.role_map,
        default_role_key=payload.default_role_key,
        auto_provision=payload.auto_provision,
        enabled=payload.enabled,
        metadata_json={"created_by": actor},
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return idp_view(row)


@app.post("/api/enterprise/identity-providers/{provider_key}/discover")
async def discover_identity_provider(
    provider_key: str,
    _: str = Depends(require_governance("enterprise:sso:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(select(IdentityProvider).where(IdentityProvider.provider_key == provider_key))
    if row is None:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    try:
        metadata = await discover_oidc(row)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OIDC discovery failed: {exc}") from exc
    db.commit()
    db.refresh(row)
    return {**idp_view(row), "discovery": metadata}


@app.post("/enterprise/sso/oidc/exchange")
def exchange_oidc_token(
    payload: OIDCExchange,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    provider = db.scalar(
        select(IdentityProvider).where(IdentityProvider.provider_key == payload.provider_key)
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    try:
        claims = verify_oidc_token(provider, payload.id_token)
        membership = provision_membership(db, provider, claims)
        session, plain = issue_session(db, membership, provider.provider_key, payload.session_minutes)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=401, detail=f"OIDC exchange rejected: {exc}") from exc
    db.commit()
    return {
        "access_token": plain,
        "token_type": "Bearer",
        "expires_at": session.expires_at.isoformat(),
        "identity_key": membership.identity_key,
        "tenant_key": membership.tenant_key,
    }


@app.get("/api/enterprise/api-keys")
def list_api_keys(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:credentials:manage")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(EnterpriseApiKey)
        .where(EnterpriseApiKey.tenant_key == tenant_key)
        .order_by(EnterpriseApiKey.created_at.desc())
    ).all()
    return [api_key_view(row) for row in rows]


@app.post("/api/enterprise/api-keys", status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("enterprise:credentials:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == payload.identity_key,
            GovernanceIdentity.tenant_key == tenant_key,
            GovernanceIdentity.status == "ACTIVE",
        )
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Active tenant identity not found")
    plain = random_token(API_KEY_PREFIX)
    now = utcnow()
    row = EnterpriseApiKey(
        key_id=f"KEY-{uuid4().hex[:16].upper()}",
        token_hash=token_hash(plain),
        prefix=plain[:16],
        tenant_key=tenant_key,
        identity_key=payload.identity_key,
        name=payload.name,
        scopes=sorted(set(payload.scopes)),
        rate_limit_per_minute=payload.rate_limit_per_minute,
        expires_at=now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None,
        last_used_at=None,
        revoked_at=None,
        created_by=actor,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**api_key_view(row), "token": plain}


@app.delete("/api/enterprise/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    actor: str = Depends(require_governance("enterprise:credentials:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(select(EnterpriseApiKey).where(EnterpriseApiKey.key_id == key_id))
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    row.revoked_at = utcnow()
    db.commit()
    return {"ok": True, "key_id": key_id, "revoked_by": actor}


@app.get("/api/enterprise/sites")
def list_deployment_sites(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DeploymentSite).where(DeploymentSite.tenant_key == tenant_key).order_by(DeploymentSite.name)
    ).all()
    return [site_view(row) for row in rows]


@app.get("/api/enterprise/backup/plans")
def list_backup_plans(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BackupPlan).where(BackupPlan.tenant_key == tenant_key).order_by(BackupPlan.name)
    ).all()
    return [backup_plan_view(row) for row in rows]


@app.post("/api/enterprise/backup/plans", status_code=201)
def create_backup_plan(
    payload: BackupPlanCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("enterprise:backup:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    now = utcnow()
    row = BackupPlan(
        plan_key=f"BKP-{uuid4().hex[:14].upper()}",
        tenant_key=tenant_key,
        name=payload.name,
        schedule=payload.schedule,
        retention_days=payload.retention_days,
        targets=sorted(set(payload.targets)),
        destination=payload.destination,
        encryption_key_ref=payload.encryption_key_ref,
        immutable=payload.immutable,
        enabled=True,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return backup_plan_view(row)


@app.get("/api/enterprise/backup/runs")
def list_backup_runs(
    tenant_key: str = Depends(tenant_header),
    limit: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BackupRun)
        .where(BackupRun.tenant_key == tenant_key)
        .order_by(BackupRun.started_at.desc())
        .limit(limit)
    ).all()
    return [backup_run_view(row) for row in rows]


@app.post("/api/enterprise/backup/plans/{plan_key}/runs", status_code=202)
def request_backup_run(
    plan_key: str,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("enterprise:backup:run")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    plan = db.scalar(
        select(BackupPlan).where(BackupPlan.plan_key == plan_key, BackupPlan.tenant_key == tenant_key)
    )
    if plan is None or not plan.enabled:
        raise HTTPException(status_code=404, detail="Enabled backup plan not found")
    manifest = backup_manifest(db, tenant_key, plan)
    row = BackupRun(
        run_key=f"BKPRUN-{uuid4().hex[:14].upper()}",
        plan_key=plan.plan_key,
        tenant_key=tenant_key,
        status="REQUESTED",
        mode="FULL",
        executor="external-backup-runner",
        manifest=manifest,
        checksum=hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest(),
        error=None,
        started_at=utcnow(),
        completed_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**backup_run_view(row), "requested_by": actor}


@app.post("/api/enterprise/backup/runs/{run_key}/complete")
def complete_backup_run(
    run_key: str,
    payload: BackupRunComplete,
    actor: str = Depends(require_governance("enterprise:backup:complete")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(select(BackupRun).where(BackupRun.run_key == run_key))
    if row is None:
        raise HTTPException(status_code=404, detail="Backup run not found")
    row.status = payload.status
    row.manifest = {**(row.manifest or {}), **payload.manifest, "completed_by": actor}
    row.checksum = payload.checksum or row.checksum
    row.error = payload.error
    row.completed_at = utcnow()
    db.commit()
    db.refresh(row)
    return backup_run_view(row)


@app.get("/api/enterprise/siem/sinks")
def list_siem_sinks(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SIEMSink).where(SIEMSink.tenant_key == tenant_key).order_by(SIEMSink.name)
    ).all()
    return [siem_view(row) for row in rows]


@app.post("/api/enterprise/siem/sinks", status_code=201)
def create_siem_sink(
    payload: SIEMSinkCreate,
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("enterprise:siem:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    now = utcnow()
    row = SIEMSink(
        sink_key=f"SIEM-{uuid4().hex[:14].upper()}",
        tenant_key=tenant_key,
        name=payload.name,
        sink_type=payload.sink_type,
        endpoint=payload.endpoint,
        format=payload.format,
        enabled=payload.enabled,
        last_audit_id=0,
        settings=payload.settings,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return siem_view(row)


@app.get("/api/enterprise/siem/export")
def export_siem_records(
    tenant_key: str = Depends(tenant_header),
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
    _: str = Depends(require_governance("enterprise:siem:operate")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    records = audit_export(db, tenant_key, after_id, limit)
    return {
        "tenant_key": tenant_key,
        "records": records,
        "next_after_id": records[-1]["id"] if records else after_id,
        "count": len(records),
        "hash_chain_preserved": True,
    }


@app.post("/api/enterprise/siem/sinks/{sink_key}/checkpoint")
def checkpoint_siem_sink(
    sink_key: str,
    last_audit_id: int = Query(ge=0),
    actor: str = Depends(require_governance("enterprise:siem:operate")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(select(SIEMSink).where(SIEMSink.sink_key == sink_key))
    if row is None:
        raise HTTPException(status_code=404, detail="SIEM sink not found")
    row.last_audit_id = max(row.last_audit_id, last_audit_id)
    row.settings = {**(row.settings or {}), "checkpointed_by": actor, "checkpointed_at": utcnow().isoformat()}
    row.updated_at = utcnow()
    db.commit()
    return siem_view(row)
