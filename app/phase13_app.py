from __future__ import annotations

import asyncio
import contextlib
import os
import re
from datetime import timedelta
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import governance_service
import phase12_bootstrap  # noqa: F401 — install Phase 1–12 enterprise runtime
from business_models import (
    BillingPlan,
    ExecutiveSnapshot,
    IndustryPack,
    OutcomeRecord,
    OutcomeUpsert,
    PackInstallCreate,
    PackInstallation,
    SnapshotCreate,
    SubscriptionCreate,
    TenantSubscription,
    UsageDaily,
)
from business_service import (
    agent_economics,
    billing_summary,
    create_snapshot,
    department_scorecards,
    executive_dashboard,
    outcome_view,
    pack_view,
    period_outcomes,
    plan_view,
    record_usage,
    seed_business,
    snapshot_view,
    subscription_view,
    sync_outcomes,
    usage_view,
)
from collaboration_models import CollaborationTask
from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT, resource_tenant
from governance_models import GovernanceIdentity, GovernanceRole
from main import SessionLocal, app, db_session, redis_client, utcnow
from phase6_app import require_governance
from phase12_app import tenant_header

app.version = "0.14.0"
BUSINESS_ENABLED = os.getenv("BEEZA_BUSINESS_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
BUSINESS_INTERVAL = max(30, int(os.getenv("BEEZA_BUSINESS_INTERVAL_SECONDS", "60")))
_business_worker_task: asyncio.Task[None] | None = None

_PHASE13_RULES = [
    ("POST", re.compile(r"^/api/business/sync$"), "business:sync"),
    ("POST", re.compile(r"^/api/business/outcomes$"), "business:outcome:write"),
    ("POST", re.compile(r"^/api/business/snapshots$"), "business:snapshot"),
    ("POST", re.compile(r"^/api/business/subscription$"), "business:billing:manage"),
    ("POST", re.compile(r"^/api/business/industry-packs/[^/]+/install$"), "business:pack:install"),
]
for rule in reversed(_PHASE13_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.update(
    {"business:billing:manage", "business:pack:install"}
)


def ensure_business_permissions(db: Session) -> None:
    additions = {
        "role:executive": {
            "business:read", "business:sync", "business:outcome:write",
            "business:snapshot", "business:billing:manage", "business:pack:install",
        },
        "role:manager": {
            "business:read", "business:sync", "business:outcome:write",
            "business:snapshot", "business:pack:install",
        },
        "role:operator": {"business:read", "business:sync", "business:snapshot"},
        "role:auditor": {"business:read"},
        "role:service": {"business:read", "business:sync", "business:outcome:write"},
        "role:agent": {"business:read"},
        "role:runtime": {"business:read"},
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


def sync_tenant_with_lock(db: Session, tenant_key: str) -> dict[str, Any]:
    lock = f"beezaoffice:business-sync:{tenant_key}"
    if not redis_client.set(lock, "1", nx=True, ex=max(30, BUSINESS_INTERVAL)):
        return {"tenant_key": tenant_key, "locked": True, "created": 0, "updated": 0}
    try:
        return {"tenant_key": tenant_key, "locked": False, **sync_outcomes(db, tenant_key)}
    finally:
        redis_client.delete(lock)


def business_tick() -> dict[str, Any]:
    results = []
    with SessionLocal() as db:
        tenant_keys = list(
            db.scalars(
                select(EnterpriseTenant.tenant_key).where(EnterpriseTenant.status == "ACTIVE")
            ).all()
        )
        for tenant_key in tenant_keys:
            try:
                results.append(sync_tenant_with_lock(db, tenant_key))
            except Exception as exc:
                db.rollback()
                results.append({"tenant_key": tenant_key, "error": str(exc)[:1000]})
    processed = sum(item.get("created", 0) + item.get("updated", 0) for item in results)
    redis_client.hset(
        "beezaoffice:business-worker",
        mapping={
            "status": "running",
            "last_tick_at": utcnow().isoformat(),
            "last_processed": processed,
            "last_tenants": len(results),
            "interval_seconds": BUSINESS_INTERVAL,
        },
    )
    return {"tenants": results, "processed": processed}


async def business_worker() -> None:
    redis_client.hset(
        "beezaoffice:business-worker",
        mapping={"status": "running", "interval_seconds": BUSINESS_INTERVAL},
    )
    while True:
        try:
            await asyncio.to_thread(business_tick)
        except Exception as exc:
            redis_client.hset(
                "beezaoffice:business-worker",
                mapping={"status": "degraded", "last_error": str(exc)[:1000]},
            )
        await asyncio.sleep(BUSINESS_INTERVAL)


@app.on_event("startup")
async def start_business_layer() -> None:
    global _business_worker_task
    with SessionLocal() as db:
        ensure_business_permissions(db)
        seed_business(db)
    if not BUSINESS_ENABLED:
        redis_client.hset("beezaoffice:business-worker", mapping={"status": "disabled"})
        return
    if _business_worker_task is None or _business_worker_task.done():
        _business_worker_task = asyncio.create_task(
            business_worker(), name="beeza-business-worker"
        )


@app.on_event("shutdown")
async def stop_business_layer() -> None:
    global _business_worker_task
    if _business_worker_task is None:
        return
    _business_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _business_worker_task
    _business_worker_task = None


def meter_for_request(request: Request) -> list[str]:
    path = request.url.path
    method = request.method.upper()
    meters = ["api_requests"]
    if method == "POST" and (
        re.match(r"^/api/runtimes/[^/]+/dispatch$", path)
        or re.match(r"^/api/runtime-dispatches/[^/]+/(sync|stop|approve)$", path)
    ):
        meters.append("runtime_dispatches")
    if method == "POST" and path in {"/message:send", "/v1/chat/completions", "/mcp"}:
        meters.append("external_tasks")
    if method == "POST" and path.startswith("/hooks/"):
        meters.append("external_tasks")
    if method == "POST" and re.match(r"^/api/sop/templates/[^/]+/runs$", path):
        meters.append("sop_runs")
    if method == "POST" and re.match(r"^/api/enterprise/backup/plans/[^/]+/runs$", path):
        meters.append("backup_runs")
    if method == "POST" and re.match(r"^/api/business/industry-packs/[^/]+/install$", path):
        meters.append("pack_installs")
    return meters


@app.middleware("http")
async def business_usage_meter(request: Request, call_next: Callable):
    response = await call_next(request)
    path = request.url.path
    if (
        response.status_code >= 500
        or path.startswith("/static/")
        or path in {"/health/live", "/health/ready", "/metrics", "/favicon.ico"}
    ):
        return response
    tenant_key = response.headers.get(
        "X-Beeza-Tenant",
        request.headers.get("X-Beeza-Tenant", DEFAULT_TENANT),
    )
    identity_key = request.headers.get("X-Beeza-Identity", "human:owner")
    try:
        with SessionLocal() as db:
            for meter in meter_for_request(request):
                record_usage(
                    db,
                    tenant_key,
                    meter,
                    metadata={
                        "method": request.method,
                        "path": path[:500],
                        "identity": identity_key[:180],
                        "status": response.status_code,
                    },
                )
            db.commit()
    except Exception:
        pass
    return response


@app.get("/api/business/status")
def business_status(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    worker = redis_client.hgetall("beezaoffice:business-worker")
    return {
        "enabled": BUSINESS_ENABLED,
        "version": app.version,
        "tenant_key": tenant_key,
        "worker": {
            "status": worker.get("status", "starting"),
            "last_tick_at": worker.get("last_tick_at"),
            "last_processed": int(worker.get("last_processed", "0") or 0),
            "last_tenants": int(worker.get("last_tenants", "0") or 0),
            "interval_seconds": int(worker.get("interval_seconds", str(BUSINESS_INTERVAL))),
            "last_error": worker.get("last_error"),
        },
        "outcomes": db.scalar(
            select(func.count(OutcomeRecord.id)).where(OutcomeRecord.tenant_key == tenant_key)
        ) or 0,
        "snapshots": db.scalar(
            select(func.count(ExecutiveSnapshot.id)).where(ExecutiveSnapshot.tenant_key == tenant_key)
        ) or 0,
        "installed_packs": db.scalar(
            select(func.count(PackInstallation.id)).where(
                PackInstallation.tenant_key == tenant_key,
                PackInstallation.status == "INSTALLED",
            )
        ) or 0,
    }


@app.post("/api/business/sync")
def sync_business_outcomes(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:sync")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return sync_tenant_with_lock(db, tenant_key)


@app.get("/api/business/executive")
def read_executive_dashboard(
    days: int = Query(default=30, ge=1, le=3660),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return executive_dashboard(db, tenant_key, days)


@app.get("/api/business/departments")
def read_department_scorecards(
    days: int = Query(default=30, ge=1, le=3660),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    return department_scorecards(db, tenant_key, period_outcomes(db, tenant_key, days))


@app.get("/api/business/agents")
def read_agent_economics(
    days: int = Query(default=30, ge=1, le=3660),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    return agent_economics(db, tenant_key, period_outcomes(db, tenant_key, days))


@app.get("/api/business/outcomes")
def list_business_outcomes(
    mission_key: str | None = Query(default=None, max_length=80),
    department_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    source_mode: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=200, ge=1, le=2000),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(OutcomeRecord).where(OutcomeRecord.tenant_key == tenant_key)
    if mission_key:
        statement = statement.where(OutcomeRecord.mission_key == mission_key)
    if department_key:
        statement = statement.where(OutcomeRecord.department_key == department_key)
    if status:
        statement = statement.where(OutcomeRecord.status == status.upper())
    if source_mode:
        statement = statement.where(OutcomeRecord.source_mode == source_mode.upper())
    rows = db.scalars(statement.order_by(OutcomeRecord.updated_at.desc()).limit(limit)).all()
    return [outcome_view(row) for row in rows]


@app.post("/api/business/outcomes", status_code=201)
def upsert_manual_outcome(
    payload: OutcomeUpsert,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("business:outcome:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    owner = resource_tenant(db, "mission", payload.mission_key) or DEFAULT_TENANT
    if owner != tenant_key:
        raise HTTPException(status_code=404, detail="Mission not found")
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == payload.task_key,
            CollaborationTask.mission_key == payload.mission_key,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    now = utcnow()
    row = db.scalar(
        select(OutcomeRecord).where(
            OutcomeRecord.tenant_key == tenant_key,
            OutcomeRecord.task_key == payload.task_key,
        )
    )
    hours_saved = max(0.0, payload.baseline_minutes - payload.actual_minutes) / 60.0
    cost_saved = max(0.0, payload.baseline_cost_usd - payload.actual_cost_usd)
    values = {
        "mission_key": payload.mission_key,
        "department_key": payload.department_key,
        "agent_identity": payload.agent_identity or task.target_identity,
        "category": payload.category,
        "status": payload.status,
        "source_mode": "MANUAL",
        "quality_score": payload.quality_score,
        "evidence_count": payload.evidence_count,
        "baseline_minutes": payload.baseline_minutes,
        "actual_minutes": payload.actual_minutes,
        "hours_saved": round(hours_saved, 4),
        "baseline_cost_usd": payload.baseline_cost_usd,
        "actual_cost_usd": payload.actual_cost_usd,
        "cost_saved_usd": round(cost_saved, 4),
        "revenue_value_usd": payload.revenue_value_usd,
        "sla_target_minutes": payload.sla_target_minutes,
        "sla_met": payload.sla_target_minutes > 0 and payload.actual_minutes <= payload.sla_target_minutes,
        "result_hash": payload.result_hash,
        "assumptions": {"estimated": False, "entered_by": actor},
        "metadata_json": payload.metadata,
        "verified_at": now,
        "updated_at": now,
    }
    if row is None:
        row = OutcomeRecord(
            outcome_key=f"OUT-{uuid4().hex[:14].upper()}",
            tenant_key=tenant_key,
            task_key=payload.task_key,
            created_at=now,
            **values,
        )
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    record_usage(db, tenant_key, "verified_outcomes", quantity=1)
    db.commit()
    db.refresh(row)
    return outcome_view(row)


@app.get("/api/business/snapshots")
def list_executive_snapshots(
    limit: int = Query(default=100, ge=1, le=1000),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ExecutiveSnapshot)
        .where(ExecutiveSnapshot.tenant_key == tenant_key)
        .order_by(ExecutiveSnapshot.created_at.desc())
        .limit(limit)
    ).all()
    return [snapshot_view(row) for row in rows]


@app.post("/api/business/snapshots", status_code=201)
def capture_executive_snapshot(
    payload: SnapshotCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("business:snapshot")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return snapshot_view(create_snapshot(db, tenant_key, payload.days, actor))


@app.get("/api/business/plans")
def list_billing_plans(
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BillingPlan).where(BillingPlan.status == "ACTIVE").order_by(BillingPlan.monthly_price_usd)
    ).all()
    return [plan_view(row) for row in rows]


@app.get("/api/business/billing")
def read_billing_summary(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return billing_summary(db, tenant_key)


@app.get("/api/business/usage")
def list_business_usage(
    days: int = Query(default=31, ge=1, le=3660),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    cutoff = utcnow().date() - timedelta(days=days - 1)
    rows = db.scalars(
        select(UsageDaily)
        .where(UsageDaily.tenant_key == tenant_key, UsageDaily.usage_date >= cutoff)
        .order_by(UsageDaily.usage_date.desc(), UsageDaily.meter)
    ).all()
    return [usage_view(row) for row in rows]


@app.post("/api/business/subscription")
def set_tenant_subscription(
    payload: SubscriptionCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("business:billing:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    plan = db.scalar(
        select(BillingPlan).where(
            BillingPlan.plan_key == payload.plan_key,
            BillingPlan.status == "ACTIVE",
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Billing plan not found")
    tenant = db.scalar(
        select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == tenant_key)
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    now = utcnow()
    row = db.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_key == tenant_key)
    )
    if row is None:
        row = TenantSubscription(
            subscription_key=f"SUB-{uuid4().hex[:14].upper()}",
            tenant_key=tenant_key,
            plan_key=plan.plan_key,
            status="ACTIVE",
            currency=payload.currency.upper(),
            billing_day=payload.billing_day,
            contract_value_usd=payload.contract_value_usd,
            settings=payload.settings,
            starts_at=now,
            ends_at=None,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.plan_key = plan.plan_key
        row.status = "ACTIVE"
        row.currency = payload.currency.upper()
        row.billing_day = payload.billing_day
        row.contract_value_usd = payload.contract_value_usd
        row.settings = payload.settings
        row.ends_at = None
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return subscription_view(row)


@app.get("/api/business/industry-packs")
def list_industry_packs(
    industry: str | None = Query(default=None, max_length=100),
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("business:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(IndustryPack).where(IndustryPack.status == "PUBLISHED")
    if industry:
        statement = statement.where(IndustryPack.industry == industry)
    rows = db.scalars(statement.order_by(IndustryPack.industry, IndustryPack.name)).all()
    installed = set(
        db.scalars(
            select(PackInstallation.pack_key).where(
                PackInstallation.tenant_key == tenant_key,
                PackInstallation.status == "INSTALLED",
            )
        ).all()
    )
    return [pack_view(row, row.pack_key in installed) for row in rows]


@app.post("/api/business/industry-packs/{pack_key}/install", status_code=201)
def install_industry_pack(
    pack_key: str,
    payload: PackInstallCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("business:pack:install")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    pack = db.scalar(
        select(IndustryPack).where(
            IndustryPack.pack_key == pack_key,
            IndustryPack.status == "PUBLISHED",
        )
    )
    if pack is None:
        raise HTTPException(status_code=404, detail="Industry pack not found")
    now = utcnow()
    row = db.scalar(
        select(PackInstallation).where(
            PackInstallation.tenant_key == tenant_key,
            PackInstallation.pack_key == pack_key,
        )
    )
    created = row is None
    if row is None:
        row = PackInstallation(
            installation_key=f"PACKINST-{uuid4().hex[:12].upper()}",
            tenant_key=tenant_key,
            pack_key=pack_key,
            status="INSTALLED",
            settings={
                **payload.settings,
                "asset_manifest": {
                    "sop_templates": pack.sop_templates,
                    "capabilities": pack.capabilities,
                    "required_connectors": pack.required_connectors,
                },
            },
            installed_by=actor,
            installed_at=now,
            updated_at=now,
        )
        db.add(row)
        pack.install_count += 1
        pack.updated_at = now
    else:
        row.status = "INSTALLED"
        row.settings = {
            **(row.settings or {}),
            **payload.settings,
            "asset_manifest": {
                "sop_templates": pack.sop_templates,
                "capabilities": pack.capabilities,
                "required_connectors": pack.required_connectors,
            },
        }
        row.installed_by = actor
        row.updated_at = now
    record_usage(db, tenant_key, "pack_installs", quantity=1)
    db.commit()
    db.refresh(row)
    return {
        "key": row.installation_key,
        "tenant_key": tenant_key,
        "pack": pack_view(pack, True),
        "status": row.status,
        "settings": row.settings,
        "created": created,
        "installed_by": row.installed_by,
        "installed_at": row.installed_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "activation_note": "Pack assets are installed as a governed manifest. Connectors and SOP implementations must be configured and verified before production use.",
    }
