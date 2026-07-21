from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from business_models import (
    BillingPlan,
    ExecutiveSnapshot,
    IndustryPack,
    OutcomeRecord,
    PackInstallation,
    TenantSubscription,
    UsageDaily,
)
from collaboration_models import CollaborationTask
from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT, scoped_keys
from evaluation_models import EvaluationRun
from governance_models import BudgetLedger, Department, GovernanceIdentity
from main import Mission, utcnow
from registry_models import RegisteredAgent


PRIORITY_BASELINE_MINUTES = {
    "CRITICAL": 120.0,
    "HIGH": 240.0,
    "NORMAL": 480.0,
    "LOW": 960.0,
}
PRIORITY_SLA_MINUTES = {
    "CRITICAL": 60.0,
    "HIGH": 240.0,
    "NORMAL": 720.0,
    "LOW": 1440.0,
}
DEFAULT_LABOR_RATE_USD = 30.0


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def outcome_view(row: OutcomeRecord) -> dict[str, Any]:
    return {
        "key": row.outcome_key,
        "tenant_key": row.tenant_key,
        "mission_key": row.mission_key,
        "task_key": row.task_key,
        "department_key": row.department_key,
        "agent_identity": row.agent_identity,
        "category": row.category,
        "status": row.status,
        "source_mode": row.source_mode,
        "quality_score": row.quality_score,
        "evidence_count": row.evidence_count,
        "baseline_minutes": row.baseline_minutes,
        "actual_minutes": row.actual_minutes,
        "hours_saved": row.hours_saved,
        "baseline_cost_usd": row.baseline_cost_usd,
        "actual_cost_usd": row.actual_cost_usd,
        "cost_saved_usd": row.cost_saved_usd,
        "revenue_value_usd": row.revenue_value_usd,
        "value_created_usd": round(row.cost_saved_usd + row.revenue_value_usd, 4),
        "sla_target_minutes": row.sla_target_minutes,
        "sla_met": row.sla_met,
        "result_hash": row.result_hash,
        "assumptions": row.assumptions,
        "metadata": row.metadata_json,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def plan_view(row: BillingPlan) -> dict[str, Any]:
    return {
        "key": row.plan_key,
        "name": row.name,
        "status": row.status,
        "monthly_price_usd": row.monthly_price_usd,
        "included_units": row.included_units,
        "overage_rates": row.overage_rates,
        "features": row.features,
        "deployment_mode": row.deployment_mode,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def subscription_view(row: TenantSubscription) -> dict[str, Any]:
    return {
        "key": row.subscription_key,
        "tenant_key": row.tenant_key,
        "plan_key": row.plan_key,
        "status": row.status,
        "currency": row.currency,
        "billing_day": row.billing_day,
        "contract_value_usd": row.contract_value_usd,
        "settings": row.settings,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def usage_view(row: UsageDaily) -> dict[str, Any]:
    return {
        "tenant_key": row.tenant_key,
        "date": row.usage_date.isoformat(),
        "meter": row.meter,
        "quantity": row.quantity,
        "cost_usd": row.cost_usd,
        "metadata": row.metadata_json,
        "updated_at": row.updated_at.isoformat(),
    }


def pack_view(row: IndustryPack, installed: bool = False) -> dict[str, Any]:
    return {
        "key": row.pack_key,
        "name": row.name,
        "industry": row.industry,
        "version": row.version,
        "status": row.status,
        "description": row.description,
        "price_usd": row.price_usd,
        "capabilities": row.capabilities,
        "sop_templates": row.sop_templates,
        "required_connectors": row.required_connectors,
        "configuration": row.configuration,
        "install_count": row.install_count,
        "installed": installed,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def snapshot_view(row: ExecutiveSnapshot) -> dict[str, Any]:
    return {
        "key": row.snapshot_key,
        "tenant_key": row.tenant_key,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "metrics": row.metrics,
        "department_scorecards": row.department_scorecards,
        "agent_economics": row.agent_economics,
        "integrity_hash": row.integrity_hash,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def seed_business(db: Session) -> None:
    now = utcnow()
    plans = [
        {
            "key": "plan:team",
            "name": "Team",
            "price": 499.0,
            "included": {"api_requests": 100000, "runtime_dispatches": 5000, "verified_outcomes": 1000},
            "overage": {"api_requests": 0.0005, "runtime_dispatches": 0.08, "verified_outcomes": 0.25},
            "features": ["Mission Control", "Runtime Mesh", "Evaluation", "SOP", "A2A", "MCP"],
            "mode": "PRIVATE",
        },
        {
            "key": "plan:enterprise",
            "name": "Enterprise",
            "price": 2499.0,
            "included": {"api_requests": 1000000, "runtime_dispatches": 50000, "verified_outcomes": 10000},
            "overage": {"api_requests": 0.0002, "runtime_dispatches": 0.05, "verified_outcomes": 0.15},
            "features": ["Multi-tenant", "OIDC", "API Keys", "SIEM", "Backup", "Executive KPIs"],
            "mode": "ENTERPRISE",
        },
        {
            "key": "plan:sovereign",
            "name": "Sovereign",
            "price": 4999.0,
            "included": {"api_requests": 5000000, "runtime_dispatches": 250000, "verified_outcomes": 50000},
            "overage": {"api_requests": 0.0001, "runtime_dispatches": 0.03, "verified_outcomes": 0.10},
            "features": ["On-premises", "Air-gap", "Kubernetes HA", "DR", "Object Lock", "Industry Packs"],
            "mode": "SOVEREIGN",
        },
    ]
    for spec in plans:
        row = db.scalar(select(BillingPlan).where(BillingPlan.plan_key == spec["key"]))
        if row is None:
            db.add(
                BillingPlan(
                    plan_key=spec["key"],
                    name=spec["name"],
                    status="ACTIVE",
                    monthly_price_usd=spec["price"],
                    included_units=spec["included"],
                    overage_rates=spec["overage"],
                    features=spec["features"],
                    deployment_mode=spec["mode"],
                    created_at=now,
                    updated_at=now,
                )
            )

    packs = [
        {
            "key": "pack:government-document-ops",
            "name": "Government Document Operations",
            "industry": "Government",
            "description": "Complaint intake, official-letter drafting, evidence packs, approval gates and executive reporting.",
            "price": 12000.0,
            "capabilities": ["Thai official documents", "complaint classification", "approval workflow", "evidence export"],
            "sops": ["government-complaint-pack", "official-letter-review", "executive-report"],
            "connectors": ["Google Drive or sovereign object storage", "Email or LINE gateway"],
        },
        {
            "key": "pack:idc-soc-incident-command",
            "name": "IDC & SOC Incident Command",
            "industry": "Telecom & Infrastructure",
            "description": "Multi-layer incident triage, evidence collection, change approval, verification and runbook capture.",
            "price": 18000.0,
            "capabilities": ["L2-L7 triage", "SIEM evidence", "change approval", "post-incident report"],
            "sops": ["incident-triage", "production-remediation", "post-incident-review"],
            "connectors": ["SIEM", "Prometheus", "Ticketing", "Runtime Mesh"],
        },
        {
            "key": "pack:finance-cfo-office",
            "name": "AI CFO Office",
            "industry": "Finance & Startup",
            "description": "Cash-flow review, accounting close, tax checklist, board pack and investment decision support.",
            "price": 15000.0,
            "capabilities": ["cash flow", "management accounting", "tax checklist", "board reporting"],
            "sops": ["monthly-close", "cash-runway", "board-finance-pack"],
            "connectors": ["Accounting system", "Bank export", "Google Drive"],
        },
        {
            "key": "pack:customer-support-operations",
            "name": "Customer Support Operations",
            "industry": "Customer Service",
            "description": "Omnichannel intake, knowledge retrieval, escalation, quality review and SLA analytics.",
            "price": 8000.0,
            "capabilities": ["omnichannel", "knowledge assistant", "escalation", "SLA scorecard"],
            "sops": ["support-resolution", "complaint-escalation", "quality-review"],
            "connectors": ["LINE", "Email", "CRM", "Knowledge Base"],
        },
    ]
    for spec in packs:
        row = db.scalar(select(IndustryPack).where(IndustryPack.pack_key == spec["key"]))
        if row is None:
            db.add(
                IndustryPack(
                    pack_key=spec["key"],
                    name=spec["name"],
                    industry=spec["industry"],
                    version="1.0.0",
                    status="PUBLISHED",
                    description=spec["description"],
                    price_usd=spec["price"],
                    capabilities=spec["capabilities"],
                    sop_templates=spec["sops"],
                    required_connectors=spec["connectors"],
                    configuration={"verification_required": True, "governance_required": True},
                    install_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )

    tenant = db.scalar(select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == DEFAULT_TENANT))
    subscription = db.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_key == DEFAULT_TENANT)
    )
    if tenant is not None and subscription is None:
        db.add(
            TenantSubscription(
                subscription_key=f"SUB-{uuid4().hex[:14].upper()}",
                tenant_key=DEFAULT_TENANT,
                plan_key="plan:sovereign",
                status="ACTIVE",
                currency="USD",
                billing_day=1,
                contract_value_usd=0.0,
                settings={"seeded": True, "billing_mode": "internal"},
                starts_at=now,
                ends_at=None,
                created_by="system:phase13",
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()


def record_usage(
    db: Session,
    tenant_key: str,
    meter: str,
    quantity: float = 1.0,
    cost_usd: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> None:
    today = utcnow().date()
    statement = pg_insert(UsageDaily).values(
        tenant_key=tenant_key,
        usage_date=today,
        meter=meter,
        quantity=float(quantity),
        cost_usd=float(cost_usd),
        metadata_json=metadata or {},
        updated_at=utcnow(),
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_business_usage_daily",
        set_={
            "quantity": UsageDaily.quantity + float(quantity),
            "cost_usd": UsageDaily.cost_usd + float(cost_usd),
            "metadata_json": metadata or {},
            "updated_at": utcnow(),
        },
    )
    db.execute(statement)


def task_department(
    task: CollaborationTask,
    identities: dict[str, GovernanceIdentity],
    agents: dict[str, RegisteredAgent],
) -> str | None:
    identity = identities.get(task.target_identity)
    if identity and identity.department_key:
        return identity.department_key
    agent = agents.get(task.target_identity) or agents.get(task.target_identity.removeprefix("agent:"))
    return agent.department_key if agent else None


def sync_outcomes(db: Session, tenant_key: str) -> dict[str, int]:
    mission_keys = scoped_keys(db, "mission", tenant_key)
    if not mission_keys:
        return {"evaluations": 0, "created": 0, "updated": 0, "preserved_manual": 0}

    evaluations = list(
        db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.mission_key.in_(mission_keys))
            .order_by(EvaluationRun.created_at)
        ).all()
    )
    latest: dict[str, EvaluationRun] = {}
    for row in evaluations:
        latest[row.task_key] = row
    task_keys = list(latest)
    if not task_keys:
        return {"evaluations": 0, "created": 0, "updated": 0, "preserved_manual": 0}

    tasks = {
        row.task_key: row
        for row in db.scalars(
            select(CollaborationTask).where(CollaborationTask.task_key.in_(task_keys))
        ).all()
    }
    missions = {
        row.mission_key: row
        for row in db.scalars(select(Mission).where(Mission.mission_key.in_(mission_keys))).all()
    }
    identities = {
        row.identity_key: row
        for row in db.scalars(
            select(GovernanceIdentity).where(GovernanceIdentity.tenant_key == tenant_key)
        ).all()
    }
    agents: dict[str, RegisteredAgent] = {}
    for row in db.scalars(
        select(RegisteredAgent)
        .join(GovernanceIdentity, GovernanceIdentity.identity_key == RegisteredAgent.identity_key)
        .where(GovernanceIdentity.tenant_key == tenant_key)
    ).all():
        agents[row.identity_key] = row
        agents[row.agent_key] = row
        agents[f"agent:{row.display_name}"] = row

    ledger_rows = list(
        db.scalars(
            select(BudgetLedger).where(
                BudgetLedger.mission_key.in_(mission_keys),
                BudgetLedger.entry_type.in_(["CHARGE", "ADJUST"]),
            )
        ).all()
    )
    direct_cost: dict[str, float] = defaultdict(float)
    unassigned_cost: dict[str, float] = defaultdict(float)
    for row in ledger_rows:
        amount = float(row.amount_usd or 0.0)
        details = row.details or {}
        task_key = str(details.get("task_key") or row.reference_key or "")
        if task_key in latest:
            direct_cost[task_key] += amount
        elif row.mission_key:
            unassigned_cost[row.mission_key] += amount
    tasks_per_mission: dict[str, int] = defaultdict(int)
    for evaluation in latest.values():
        tasks_per_mission[evaluation.mission_key] += 1

    created = updated = preserved = 0
    now = utcnow()
    for task_key, evaluation in latest.items():
        task = tasks.get(task_key)
        mission = missions.get(evaluation.mission_key)
        if task is None or mission is None:
            continue
        existing = db.scalar(
            select(OutcomeRecord).where(
                OutcomeRecord.tenant_key == tenant_key,
                OutcomeRecord.task_key == task_key,
            )
        )
        if existing is not None and existing.source_mode in {"MANUAL", "IMPORTED"}:
            preserved += 1
            continue

        context = task.context or {}
        actual_minutes = max(
            0.01,
            ((aware(evaluation.created_at) or now) - (aware(task.created_at) or now)).total_seconds() / 60.0,
        )
        baseline_minutes = float(
            context.get("business_baseline_minutes")
            or context.get("baseline_minutes")
            or max(actual_minutes * 1.8, PRIORITY_BASELINE_MINUTES.get(mission.priority, 480.0))
        )
        labor_rate = float(context.get("labor_rate_usd") or DEFAULT_LABOR_RATE_USD)
        baseline_cost = float(
            context.get("baseline_cost_usd") or baseline_minutes / 60.0 * labor_rate
        )
        actual_cost = direct_cost.get(task_key, 0.0)
        actual_cost += unassigned_cost.get(mission.mission_key, 0.0) / max(
            1, tasks_per_mission[mission.mission_key]
        )
        revenue_value = float(context.get("revenue_value_usd") or 0.0)
        if task.deadline_at:
            sla_target = max(
                0.0,
                ((aware(task.deadline_at) or now) - (aware(task.created_at) or now)).total_seconds() / 60.0,
            )
        else:
            sla_target = float(
                context.get("sla_target_minutes")
                or PRIORITY_SLA_MINUTES.get(mission.priority, 720.0)
            )
        status = {
            "PASS": "VERIFIED",
            "WARN": "REVIEW",
            "FAIL": "FAILED",
            "ERROR": "FAILED",
        }.get(evaluation.status, "REVIEW")
        department_key = task_department(task, identities, agents)
        category = str(
            context.get("outcome_category")
            or context.get("category")
            or (department_key.split(":", 1)[-1].replace("-", " ").title() if department_key else "General")
        )[:100]
        hours_saved = max(0.0, baseline_minutes - actual_minutes) / 60.0
        cost_saved = max(0.0, baseline_cost - actual_cost)
        assumptions = {
            "estimated": True,
            "baseline_rule": "context override or max(actual x 1.8, priority baseline)",
            "labor_rate_usd": labor_rate,
            "mission_cost_allocation": "task-linked cost plus equal share of unassigned mission charges",
        }
        values = {
            "mission_key": mission.mission_key,
            "department_key": department_key,
            "agent_identity": task.target_identity,
            "category": category,
            "status": status,
            "source_mode": "ESTIMATED",
            "quality_score": float(evaluation.score or 0.0),
            "evidence_count": int(evaluation.evidence_count or 0),
            "baseline_minutes": round(baseline_minutes, 4),
            "actual_minutes": round(actual_minutes, 4),
            "hours_saved": round(hours_saved, 4),
            "baseline_cost_usd": round(baseline_cost, 4),
            "actual_cost_usd": round(actual_cost, 4),
            "cost_saved_usd": round(cost_saved, 4),
            "revenue_value_usd": round(revenue_value, 4),
            "sla_target_minutes": round(sla_target, 4),
            "sla_met": actual_minutes <= sla_target if sla_target > 0 else False,
            "result_hash": evaluation.result_hash,
            "assumptions": assumptions,
            "metadata_json": {
                "evaluation_key": evaluation.evaluation_key,
                "recommendation": evaluation.recommendation,
                "priority": mission.priority,
            },
            "verified_at": evaluation.created_at,
            "updated_at": now,
        }
        if existing is None:
            db.add(
                OutcomeRecord(
                    outcome_key=f"OUT-{uuid4().hex[:14].upper()}",
                    tenant_key=tenant_key,
                    task_key=task_key,
                    created_at=now,
                    **values,
                )
            )
            created += 1
        else:
            for field, value in values.items():
                setattr(existing, field, value)
            updated += 1
    record_usage(db, tenant_key, "verified_outcomes", quantity=created + updated)
    db.commit()
    return {
        "evaluations": len(latest),
        "created": created,
        "updated": updated,
        "preserved_manual": preserved,
    }


def period_bounds(days: int) -> tuple[datetime, datetime]:
    end = utcnow()
    return end - timedelta(days=days), end


def period_outcomes(db: Session, tenant_key: str, days: int) -> list[OutcomeRecord]:
    start, _ = period_bounds(days)
    return list(
        db.scalars(
            select(OutcomeRecord)
            .where(
                OutcomeRecord.tenant_key == tenant_key,
                OutcomeRecord.updated_at >= start,
                OutcomeRecord.status != "VOID",
            )
            .order_by(OutcomeRecord.updated_at.desc())
        ).all()
    )


def executive_metrics(rows: list[OutcomeRecord]) -> dict[str, Any]:
    verified = [row for row in rows if row.status == "VERIFIED"]
    reviewed = [row for row in rows if row.status == "REVIEW"]
    failed = [row for row in rows if row.status == "FAILED"]
    actual_cost = sum(row.actual_cost_usd for row in rows)
    baseline_cost = sum(row.baseline_cost_usd for row in rows)
    cost_saved = sum(row.cost_saved_usd for row in rows)
    revenue = sum(row.revenue_value_usd for row in rows)
    value_created = cost_saved + revenue
    sla_rows = [row for row in rows if row.sla_target_minutes > 0]
    return {
        "outcomes": len(rows),
        "verified": len(verified),
        "review": len(reviewed),
        "failed": len(failed),
        "verification_rate": round(len(verified) / len(rows), 4) if rows else 0.0,
        "average_quality": round(sum(row.quality_score for row in rows) / len(rows), 4) if rows else 0.0,
        "evidence_count": sum(row.evidence_count for row in rows),
        "hours_saved": round(sum(row.hours_saved for row in rows), 2),
        "baseline_cost_usd": round(baseline_cost, 2),
        "actual_cost_usd": round(actual_cost, 2),
        "cost_saved_usd": round(cost_saved, 2),
        "revenue_value_usd": round(revenue, 2),
        "value_created_usd": round(value_created, 2),
        "roi_ratio": round(value_created / actual_cost, 4) if actual_cost > 0 else None,
        "sla_measured": len(sla_rows),
        "sla_met": sum(row.sla_met for row in sla_rows),
        "sla_compliance": round(sum(row.sla_met for row in sla_rows) / len(sla_rows), 4) if sla_rows else 0.0,
        "estimated_outcomes": sum(row.source_mode == "ESTIMATED" for row in rows),
        "manual_outcomes": sum(row.source_mode in {"MANUAL", "IMPORTED"} for row in rows),
        "mission_count": len({row.mission_key for row in rows}),
    }


def department_scorecards(db: Session, tenant_key: str, rows: list[OutcomeRecord]) -> list[dict[str, Any]]:
    departments = {
        row.department_key: row
        for row in db.scalars(
            select(Department).where(Department.tenant_key == tenant_key)
        ).all()
    }
    agent_counts = dict(
        db.execute(
            select(RegisteredAgent.department_key, func.count(RegisteredAgent.id))
            .join(GovernanceIdentity, GovernanceIdentity.identity_key == RegisteredAgent.identity_key)
            .where(GovernanceIdentity.tenant_key == tenant_key, RegisteredAgent.status == "ACTIVE")
            .group_by(RegisteredAgent.department_key)
        ).all()
    )
    grouped: dict[str, list[OutcomeRecord]] = defaultdict(list)
    for row in rows:
        grouped[row.department_key or "dept:unassigned"].append(row)
    result = []
    for key, group in grouped.items():
        metrics = executive_metrics(group)
        result.append(
            {
                "department_key": key,
                "name": departments[key].name if key in departments else "Unassigned",
                "risk_tier": departments[key].risk_tier if key in departments else "NORMAL",
                "active_agents": int(agent_counts.get(key, 0)),
                **metrics,
            }
        )
    return sorted(result, key=lambda item: (item["value_created_usd"], item["verified"]), reverse=True)


def agent_economics(db: Session, tenant_key: str, rows: list[OutcomeRecord]) -> list[dict[str, Any]]:
    identities = {
        row.identity_key: row
        for row in db.scalars(
            select(GovernanceIdentity).where(GovernanceIdentity.tenant_key == tenant_key)
        ).all()
    }
    registry = {
        row.identity_key: row
        for row in db.scalars(
            select(RegisteredAgent)
            .join(GovernanceIdentity, GovernanceIdentity.identity_key == RegisteredAgent.identity_key)
            .where(GovernanceIdentity.tenant_key == tenant_key)
        ).all()
    }
    grouped: dict[str, list[OutcomeRecord]] = defaultdict(list)
    for row in rows:
        grouped[row.agent_identity or "unassigned"].append(row)
    ledger_cost = dict(
        db.execute(
            select(BudgetLedger.identity_key, func.sum(BudgetLedger.amount_usd))
            .join(GovernanceIdentity, GovernanceIdentity.identity_key == BudgetLedger.identity_key)
            .where(
                GovernanceIdentity.tenant_key == tenant_key,
                BudgetLedger.entry_type.in_(["CHARGE", "ADJUST"]),
            )
            .group_by(BudgetLedger.identity_key)
        ).all()
    )
    result = []
    for identity_key, group in grouped.items():
        identity = identities.get(identity_key)
        agent = registry.get(identity_key)
        metrics = executive_metrics(group)
        cost = float(ledger_cost.get(identity_key, metrics["actual_cost_usd"]) or 0.0)
        value = float(metrics["value_created_usd"])
        result.append(
            {
                "identity_key": identity_key,
                "name": identity.display_name if identity else (agent.display_name if agent else identity_key),
                "department_key": identity.department_key if identity else (agent.department_key if agent else None),
                "reliability_score": agent.reliability_score if agent else None,
                "total_runs": agent.total_runs if agent else 0,
                "outcomes": metrics["outcomes"],
                "verified": metrics["verified"],
                "average_quality": metrics["average_quality"],
                "hours_saved": metrics["hours_saved"],
                "cost_usd": round(cost, 2),
                "value_created_usd": round(value, 2),
                "value_cost_ratio": round(value / cost, 4) if cost > 0 else None,
                "sla_compliance": metrics["sla_compliance"],
            }
        )
    return sorted(result, key=lambda item: (item["value_created_usd"], item["verified"]), reverse=True)


def executive_dashboard(db: Session, tenant_key: str, days: int) -> dict[str, Any]:
    rows = period_outcomes(db, tenant_key, days)
    start, end = period_bounds(days)
    metrics = executive_metrics(rows)
    departments = department_scorecards(db, tenant_key, rows)
    agents = agent_economics(db, tenant_key, rows)
    trend: dict[str, dict[str, float]] = defaultdict(lambda: {"outcomes": 0.0, "verified": 0.0, "hours_saved": 0.0, "value_created_usd": 0.0})
    for row in rows:
        key = row.updated_at.date().isoformat()
        trend[key]["outcomes"] += 1
        trend[key]["verified"] += 1 if row.status == "VERIFIED" else 0
        trend[key]["hours_saved"] += row.hours_saved
        trend[key]["value_created_usd"] += row.cost_saved_usd + row.revenue_value_usd
    return {
        "tenant_key": tenant_key,
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "metrics": metrics,
        "departments": departments,
        "agents": agents,
        "trend": [
            {"date": day, **{key: round(value, 2) for key, value in values.items()}}
            for day, values in sorted(trend.items())
        ],
        "top_outcomes": [outcome_view(row) for row in rows[:20]],
        "measurement_note": "Estimated outcomes use configured baselines or priority defaults. Manual/imported records override estimates.",
    }


def create_snapshot(
    db: Session,
    tenant_key: str,
    days: int,
    actor: str,
) -> ExecutiveSnapshot:
    dashboard = executive_dashboard(db, tenant_key, days)
    start = date.fromisoformat(dashboard["period"]["start"][:10])
    end = date.fromisoformat(dashboard["period"]["end"][:10])
    canonical = json.dumps(dashboard, ensure_ascii=False, sort_keys=True, default=str)
    row = ExecutiveSnapshot(
        snapshot_key=f"SNAP-{uuid4().hex[:14].upper()}",
        tenant_key=tenant_key,
        period_start=start,
        period_end=end,
        metrics=dashboard["metrics"],
        department_scorecards=dashboard["departments"],
        agent_economics=dashboard["agents"],
        integrity_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        created_by=actor,
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def billing_summary(db: Session, tenant_key: str) -> dict[str, Any]:
    subscription = db.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_key == tenant_key)
    )
    plan = db.scalar(
        select(BillingPlan).where(BillingPlan.plan_key == subscription.plan_key)
    ) if subscription else None
    today = utcnow().date()
    period_start = today.replace(day=1)
    usage_rows = list(
        db.scalars(
            select(UsageDaily)
            .where(
                UsageDaily.tenant_key == tenant_key,
                UsageDaily.usage_date >= period_start,
                UsageDaily.usage_date <= today,
            )
            .order_by(UsageDaily.usage_date.desc(), UsageDaily.meter)
        ).all()
    )
    totals: dict[str, float] = defaultdict(float)
    direct_cost = 0.0
    for row in usage_rows:
        totals[row.meter] += row.quantity
        direct_cost += row.cost_usd
    included = plan.included_units if plan else {}
    rates = plan.overage_rates if plan else {}
    meters = []
    overage_total = 0.0
    for meter in sorted(set(totals) | set(included)):
        quantity = float(totals.get(meter, 0.0))
        included_quantity = float(included.get(meter, 0.0))
        overage = max(0.0, quantity - included_quantity)
        rate = float(rates.get(meter, 0.0))
        charge = overage * rate
        overage_total += charge
        meters.append(
            {
                "meter": meter,
                "quantity": round(quantity, 4),
                "included": round(included_quantity, 4),
                "overage": round(overage, 4),
                "rate_usd": rate,
                "charge_usd": round(charge, 4),
                "utilization": round(quantity / included_quantity, 4) if included_quantity > 0 else None,
            }
        )
    base = (
        subscription.contract_value_usd
        if subscription and subscription.contract_value_usd > 0
        else (plan.monthly_price_usd if plan else 0.0)
    )
    return {
        "tenant_key": tenant_key,
        "period_start": period_start.isoformat(),
        "period_end": today.isoformat(),
        "subscription": subscription_view(subscription) if subscription else None,
        "plan": plan_view(plan) if plan else None,
        "meters": meters,
        "base_charge_usd": round(base, 2),
        "usage_cost_usd": round(direct_cost, 2),
        "overage_charge_usd": round(overage_total, 2),
        "estimated_total_usd": round(base + direct_cost + overage_total, 2),
        "usage_daily": [usage_view(row) for row in usage_rows[:100]],
        "billing_note": "Estimated invoice only. Tax, discounts, support contracts and infrastructure pass-through are not included.",
    }
