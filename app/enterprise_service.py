from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import secrets
from datetime import timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from enterprise_models import (
    BackupPlan,
    BackupRun,
    DeploymentSite,
    EnterpriseApiKey,
    EnterpriseMembership,
    EnterpriseSession,
    EnterpriseTenant,
    IdentityProvider,
    ResourceScope,
    SIEMSink,
)
from governance_models import AuditRecord, GovernanceIdentity, RoleBinding, Tenant
from main import Mission, RuntimeDispatch, bounded_payload, redis_client, utcnow
from protocol_models import ProtocolTask
from registry_models import RegisteredAgent
from sop_models import SOPRun, SOPTemplate

DEFAULT_TENANT = os.getenv("BEEZA_DEFAULT_TENANT", "tenant:beeza").strip() or "tenant:beeza"
SESSION_PREFIX = "bzsess_"
API_KEY_PREFIX = "bzk_"


def aware(value):
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def random_token(prefix: str, bytes_count: int = 32) -> str:
    return f"{prefix}{secrets.token_urlsafe(bytes_count)}"


def tenant_slug(tenant_key: str) -> str:
    return tenant_key.split(":", 1)[-1].replace("_", "-")[:80]


def tenant_view(row: EnterpriseTenant) -> dict[str, Any]:
    return {
        "key": row.tenant_key,
        "slug": row.slug,
        "name": row.display_name,
        "status": row.status,
        "isolation_mode": row.isolation_mode,
        "data_region": row.data_region,
        "namespace": row.namespace,
        "object_store_bucket": row.object_store_bucket,
        "encryption_key_configured": bool(row.encryption_key_ref),
        "max_agents": row.max_agents,
        "max_concurrent_tasks": row.max_concurrent_tasks,
        "requests_per_minute": row.requests_per_minute,
        "retention_days": row.retention_days,
        "air_gapped": row.air_gapped,
        "settings": row.settings,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def idp_view(row: IdentityProvider) -> dict[str, Any]:
    return {
        "key": row.provider_key,
        "tenant_key": row.tenant_key,
        "name": row.name,
        "type": row.provider_type,
        "issuer_url": row.issuer_url,
        "client_id": row.client_id,
        "audience": row.audience,
        "jwks_uri": row.jwks_uri,
        "authorization_endpoint": row.authorization_endpoint,
        "token_endpoint": row.token_endpoint,
        "allowed_algorithms": row.allowed_algorithms,
        "subject_claim": row.subject_claim,
        "email_claim": row.email_claim,
        "groups_claim": row.groups_claim,
        "role_map": row.role_map,
        "default_role_key": row.default_role_key,
        "auto_provision": row.auto_provision,
        "enabled": row.enabled,
        "metadata": row.metadata_json,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def api_key_view(row: EnterpriseApiKey) -> dict[str, Any]:
    return {
        "key_id": row.key_id,
        "prefix": row.prefix,
        "tenant_key": row.tenant_key,
        "identity_key": row.identity_key,
        "name": row.name,
        "scopes": row.scopes,
        "rate_limit_per_minute": row.rate_limit_per_minute,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def backup_plan_view(row: BackupPlan) -> dict[str, Any]:
    return {
        "key": row.plan_key,
        "tenant_key": row.tenant_key,
        "name": row.name,
        "schedule": row.schedule,
        "retention_days": row.retention_days,
        "targets": row.targets,
        "destination": row.destination,
        "encryption_key_configured": bool(row.encryption_key_ref),
        "immutable": row.immutable,
        "enabled": row.enabled,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def backup_run_view(row: BackupRun) -> dict[str, Any]:
    return {
        "key": row.run_key,
        "plan_key": row.plan_key,
        "tenant_key": row.tenant_key,
        "status": row.status,
        "mode": row.mode,
        "executor": row.executor,
        "manifest": row.manifest,
        "checksum": row.checksum,
        "error": row.error,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def site_view(row: DeploymentSite) -> dict[str, Any]:
    return {
        "key": row.site_key,
        "tenant_key": row.tenant_key,
        "name": row.name,
        "type": row.site_type,
        "region": row.region,
        "status": row.status,
        "rpo_minutes": row.rpo_minutes,
        "rto_minutes": row.rto_minutes,
        "capabilities": row.capabilities,
        "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
    }


def siem_view(row: SIEMSink) -> dict[str, Any]:
    return {
        "key": row.sink_key,
        "tenant_key": row.tenant_key,
        "name": row.name,
        "type": row.sink_type,
        "endpoint": row.endpoint,
        "format": row.format,
        "enabled": row.enabled,
        "last_audit_id": row.last_audit_id,
        "settings": row.settings,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def scope_resource(
    db: Session,
    resource_type: str,
    resource_key: str,
    tenant_key: str,
    *,
    classification: str = "INTERNAL",
    namespace: str = "default",
    created_by: str = "system:phase12",
) -> ResourceScope:
    row = db.scalar(
        select(ResourceScope).where(
            ResourceScope.resource_type == resource_type,
            ResourceScope.resource_key == resource_key,
        )
    )
    if row is None:
        row = ResourceScope(
            resource_type=resource_type,
            resource_key=resource_key,
            tenant_key=tenant_key,
            namespace=namespace,
            classification=classification,
            created_by=created_by,
            created_at=utcnow(),
        )
        db.add(row)
    return row


def resource_tenant(db: Session, resource_type: str, resource_key: str) -> str | None:
    return db.scalar(
        select(ResourceScope.tenant_key).where(
            ResourceScope.resource_type == resource_type,
            ResourceScope.resource_key == resource_key,
        )
    )


def scoped_keys(db: Session, resource_type: str, tenant_key: str) -> list[str]:
    return list(
        db.scalars(
            select(ResourceScope.resource_key).where(
                ResourceScope.resource_type == resource_type,
                ResourceScope.tenant_key == tenant_key,
            )
        ).all()
    )


def seed_enterprise(db: Session) -> None:
    now = utcnow()
    governance_tenant = db.scalar(select(Tenant).where(Tenant.tenant_key == DEFAULT_TENANT))
    if governance_tenant is None:
        governance_tenant = Tenant(
            tenant_key=DEFAULT_TENANT,
            name="BeezaOffice",
            status="ACTIVE",
            data_region="on-premises",
            created_at=now,
            updated_at=now,
        )
        db.add(governance_tenant)

    tenant = db.scalar(select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == DEFAULT_TENANT))
    if tenant is None:
        tenant = EnterpriseTenant(
            tenant_key=DEFAULT_TENANT,
            slug="beeza",
            display_name="BeezaOffice",
            status="ACTIVE",
            isolation_mode="ROW",
            data_region="on-premises",
            namespace="beezaoffice",
            object_store_bucket="beeza-evidence",
            encryption_key_ref="",
            max_agents=1000,
            max_concurrent_tasks=200,
            requests_per_minute=600,
            retention_days=365,
            air_gapped=False,
            settings={"seeded": True, "deployment": "private"},
            created_at=now,
            updated_at=now,
        )
        db.add(tenant)

    if db.scalar(select(DeploymentSite.id).where(DeploymentSite.site_key == "site:primary")) is None:
        db.add(
            DeploymentSite(
                site_key="site:primary",
                tenant_key=DEFAULT_TENANT,
                name="Primary on-premises site",
                site_type="PRIMARY",
                region="on-premises",
                status="READY",
                rpo_minutes=15,
                rto_minutes=60,
                capabilities=["postgres", "redis", "object-storage", "runtime-mesh"],
                last_heartbeat_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    if db.scalar(select(BackupPlan.id).where(BackupPlan.plan_key == "backup:daily")) is None:
        db.add(
            BackupPlan(
                plan_key="backup:daily",
                tenant_key=DEFAULT_TENANT,
                name="Daily encrypted platform backup",
                schedule="0 2 * * *",
                retention_days=30,
                targets=["postgres", "redis", "evidence", "configuration"],
                destination="s3://beeza-backups/daily",
                encryption_key_ref="",
                immutable=True,
                enabled=True,
                created_by="system:phase12",
                created_at=now,
                updated_at=now,
            )
        )

    if db.scalar(select(SIEMSink.id).where(SIEMSink.sink_key == "siem:default")) is None:
        db.add(
            SIEMSink(
                sink_key="siem:default",
                tenant_key=DEFAULT_TENANT,
                name="Default SIEM export",
                sink_type="HTTP",
                endpoint="",
                format="JSONL",
                enabled=False,
                last_audit_id=0,
                settings={"delivery": "pull", "hash_chain": True},
                created_at=now,
                updated_at=now,
            )
        )

    for mission_key in db.scalars(select(Mission.mission_key)).all():
        scope_resource(db, "mission", mission_key, DEFAULT_TENANT)
    for task_id in db.scalars(select(ProtocolTask.task_id)).all():
        scope_resource(db, "protocol_task", task_id, DEFAULT_TENANT)
    for template_key in db.scalars(select(SOPTemplate.template_key)).all():
        scope_resource(db, "sop_template", template_key, DEFAULT_TENANT)
    for run_key in db.scalars(select(SOPRun.run_key)).all():
        scope_resource(db, "sop_run", run_key, DEFAULT_TENANT)
    db.commit()


async def discover_oidc(provider: IdentityProvider) -> dict[str, Any]:
    if not provider.issuer_url:
        return {}
    url = f"{provider.issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    provider.jwks_uri = str(data.get("jwks_uri") or provider.jwks_uri)
    provider.authorization_endpoint = str(data.get("authorization_endpoint") or "")
    provider.token_endpoint = str(data.get("token_endpoint") or "")
    provider.metadata_json = bounded_payload(data, max_chars=12000)
    provider.updated_at = utcnow()
    return data


def verify_oidc_token(provider: IdentityProvider, encoded: str) -> dict[str, Any]:
    if provider.provider_type != "OIDC" or not provider.enabled:
        raise ValueError("OIDC provider is disabled")
    if not provider.jwks_uri:
        raise ValueError("OIDC provider has no JWKS URI")
    signing_key = PyJWKClient(provider.jwks_uri).get_signing_key_from_jwt(encoded).key
    audience = provider.audience or provider.client_id
    options = {"require": [provider.subject_claim, "exp", "iat"]}
    return jwt.decode(
        encoded,
        signing_key,
        algorithms=provider.allowed_algorithms or ["RS256"],
        audience=audience or None,
        issuer=provider.issuer_url or None,
        options=options,
    )


def provision_membership(
    db: Session,
    provider: IdentityProvider,
    claims: dict[str, Any],
) -> EnterpriseMembership:
    subject = str(claims.get(provider.subject_claim) or "").strip()
    if not subject:
        raise ValueError("OIDC token has no subject claim")
    row = db.scalar(
        select(EnterpriseMembership).where(
            EnterpriseMembership.provider_key == provider.provider_key,
            EnterpriseMembership.external_subject == subject,
        )
    )
    now = utcnow()
    email = str(claims.get(provider.email_claim) or "")[:320]
    raw_groups = claims.get(provider.groups_claim) or []
    groups = [str(item) for item in raw_groups] if isinstance(raw_groups, list) else [str(raw_groups)]
    if row is None:
        if not provider.auto_provision:
            raise ValueError("Identity is not provisioned")
        identity_key = f"human:{tenant_slug(provider.tenant_key)}:{hashlib.sha256(subject.encode()).hexdigest()[:16]}"
        identity = GovernanceIdentity(
            identity_key=identity_key,
            tenant_key=provider.tenant_key,
            identity_type="HUMAN",
            display_name=str(claims.get("name") or email or subject)[:200],
            department_key=None,
            status="ACTIVE",
            clearance="INTERNAL",
            daily_budget_usd=50.0,
            monthly_budget_usd=1000.0,
            attributes={"provider_key": provider.provider_key, "external_subject": subject, "email": email},
            created_at=now,
            updated_at=now,
        )
        db.add(identity)
        db.flush()
        role_key = provider.default_role_key
        for group in groups:
            if group in (provider.role_map or {}):
                role_key = provider.role_map[group]
                break
        db.add(
            RoleBinding(
                binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                identity_key=identity_key,
                role_key=role_key,
                scope_type="TENANT",
                scope_key=provider.tenant_key,
                created_by="service:enterprise",
                created_at=now,
            )
        )
        row = EnterpriseMembership(
            membership_key=f"MEM-{uuid4().hex[:14].upper()}",
            tenant_key=provider.tenant_key,
            provider_key=provider.provider_key,
            external_subject=subject,
            identity_key=identity_key,
            email=email,
            groups=groups,
            status="ACTIVE",
            last_login_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if row.status != "ACTIVE":
            raise ValueError("Enterprise membership is not active")
        row.email = email
        row.groups = groups
        row.last_login_at = now
        row.updated_at = now
    db.flush()
    return row


def issue_session(
    db: Session,
    membership: EnterpriseMembership,
    provider_key: str,
    minutes: int,
) -> tuple[EnterpriseSession, str]:
    token = random_token(SESSION_PREFIX)
    now = utcnow()
    row = EnterpriseSession(
        session_key=f"SES-{uuid4().hex[:16].upper()}",
        token_hash=token_hash(token),
        tenant_key=membership.tenant_key,
        identity_key=membership.identity_key,
        provider_key=provider_key,
        expires_at=now + timedelta(minutes=minutes),
        last_seen_at=now,
        revoked_at=None,
        created_at=now,
    )
    db.add(row)
    return row, token


def authenticate_session(db: Session, token: str) -> EnterpriseSession | None:
    if not token.startswith(SESSION_PREFIX):
        return None
    row = db.scalar(select(EnterpriseSession).where(EnterpriseSession.token_hash == token_hash(token)))
    now = utcnow()
    if row is None or row.revoked_at is not None or aware(row.expires_at) <= now:
        return None
    row.last_seen_at = now
    return row


def authenticate_api_key(db: Session, token: str) -> EnterpriseApiKey | None:
    if not token.startswith(API_KEY_PREFIX):
        return None
    row = db.scalar(select(EnterpriseApiKey).where(EnterpriseApiKey.token_hash == token_hash(token)))
    now = utcnow()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at and aware(row.expires_at) <= now:
        return None
    row.last_used_at = now
    return row


def api_key_scope_allowed(row: EnterpriseApiKey, permission: str) -> bool:
    scopes = row.scopes or []
    return not scopes or any(scope == "*" or fnmatch.fnmatchcase(permission, scope) for scope in scopes)


def rate_limit(
    tenant_key: str,
    identity_key: str,
    limit: int,
) -> tuple[bool, int, int]:
    window = int(utcnow().timestamp() // 60)
    key = f"beezaoffice:rate:{tenant_key}:{identity_key}:{window}"
    count = int(redis_client.incr(key))
    if count == 1:
        redis_client.expire(key, 120)
    return count <= limit, max(0, limit - count), 60 - int(utcnow().timestamp() % 60)


def backup_manifest(db: Session, tenant_key: str, plan: BackupPlan) -> dict[str, Any]:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    audit_head = db.scalar(select(func.max(AuditRecord.id))) or 0
    return {
        "tenant_key": tenant_key,
        "plan_key": plan.plan_key,
        "targets": plan.targets,
        "destination": plan.destination,
        "immutable": plan.immutable,
        "counts": {
            "missions": len(mission_keys),
            "agents": db.scalar(
                select(func.count(RegisteredAgent.id)).join(
                    GovernanceIdentity,
                    GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
                ).where(GovernanceIdentity.tenant_key == tenant_key)
            ) or 0,
            "protocol_tasks": len(scoped_keys(db, "protocol_task", tenant_key)),
            "sop_runs": len(scoped_keys(db, "sop_run", tenant_key)),
            "runtime_dispatches": db.scalar(
                select(func.count(RuntimeDispatch.id)).where(RuntimeDispatch.mission_key.in_(mission_keys))
            ) if mission_keys else 0,
            "audit_head_id": int(audit_head),
        },
        "requested_at": utcnow().isoformat(),
        "executor_contract": {
            "postgres": "pg_dump --format=custom --compress=9",
            "redis": "redis-cli --rdb",
            "evidence": "S3-compatible versioned copy with object lock",
            "callback": "/api/enterprise/backup/runs/{run_key}/complete",
        },
    }


def audit_export(db: Session, tenant_key: str, after_id: int, limit: int) -> list[dict[str, Any]]:
    identity_keys = list(
        db.scalars(
            select(GovernanceIdentity.identity_key).where(
                GovernanceIdentity.tenant_key == tenant_key
            )
        ).all()
    )
    if not identity_keys:
        return []
    rows = list(
        db.scalars(
            select(AuditRecord)
            .where(AuditRecord.id > after_id, AuditRecord.identity_key.in_(identity_keys))
            .order_by(AuditRecord.id.asc())
            .limit(limit)
        ).all()
    )
    return [
        {
            "id": row.id,
            "audit_key": row.audit_key,
            "request_id": row.request_id,
            "identity": row.identity_key,
            "action": row.action,
            "method": row.method,
            "path": row.path,
            "resource": row.resource,
            "outcome": row.outcome,
            "status_code": row.status_code,
            "detail": row.detail,
            "source_ip": row.source_ip,
            "user_agent": row.user_agent,
            "previous_hash": row.previous_hash,
            "record_hash": row.record_hash,
            "created_at": row.created_at.isoformat(),
            "tenant_key": tenant_key,
        }
        for row in rows
    ]


def enterprise_status(db: Session, tenant_key: str) -> dict[str, Any]:
    tenant = db.scalar(select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == tenant_key))
    mission_keys = scoped_keys(db, "mission", tenant_key)
    sites = list(db.scalars(select(DeploymentSite).where(DeploymentSite.tenant_key == tenant_key)).all())
    plans = list(db.scalars(select(BackupPlan).where(BackupPlan.tenant_key == tenant_key)).all())
    last_backup = db.scalar(
        select(BackupRun)
        .where(BackupRun.tenant_key == tenant_key)
        .order_by(BackupRun.started_at.desc())
        .limit(1)
    )
    providers = list(db.scalars(select(IdentityProvider).where(IdentityProvider.tenant_key == tenant_key)).all())
    active_agents = db.scalar(
        select(func.count(RegisteredAgent.id)).join(
            GovernanceIdentity,
            GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
        ).where(
            GovernanceIdentity.tenant_key == tenant_key,
            RegisteredAgent.status == "ACTIVE",
        )
    ) or 0
    active_dispatches = 0
    if mission_keys:
        active_dispatches = db.scalar(
            select(func.count(RuntimeDispatch.id)).where(
                RuntimeDispatch.mission_key.in_(mission_keys),
                RuntimeDispatch.status.in_(["DISPATCHING", "RUNNING", "QUEUED", "WAITING_APPROVAL"]),
            )
        ) or 0
    readiness = {
        "tenant_isolation": tenant is not None and tenant.status == "ACTIVE",
        "sso_configured": any(row.enabled for row in providers),
        "backup_plan": any(row.enabled for row in plans),
        "backup_verified": bool(last_backup and last_backup.status == "COMPLETED"),
        "dr_site": any(row.site_type == "DR" and row.status == "READY" for row in sites),
        "encryption_key": bool(tenant and tenant.encryption_key_ref),
        "object_storage": bool(tenant and tenant.object_store_bucket),
        "air_gap_mode": bool(tenant and tenant.air_gapped),
    }
    score = round(sum(readiness.values()) / len(readiness) * 100)
    return {
        "tenant": tenant_view(tenant) if tenant else None,
        "readiness": readiness,
        "readiness_score": score,
        "active_agents": int(active_agents),
        "active_dispatches": int(active_dispatches),
        "mission_count": len(mission_keys),
        "sites": [site_view(row) for row in sites],
        "backup_plans": [backup_plan_view(row) for row in plans],
        "last_backup": backup_run_view(last_backup) if last_backup else None,
        "identity_providers": [idp_view(row) for row in providers],
    }
