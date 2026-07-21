from __future__ import annotations

import contextlib
import contextvars
from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import business_service
import phase13_app
from business_models import OutcomeRecord
from governance_models import BudgetLedger, GovernanceIdentity
from main import redis_client
from registry_models import RegisteredAgent

_suppress_verified_meter: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "beeza_suppress_verified_meter", default=False
)
_original_record_usage = business_service.record_usage
_original_sync_outcomes = business_service.sync_outcomes


def hardened_record_usage(
    db: Session,
    tenant_key: str,
    meter: str,
    quantity: float = 1.0,
    cost_usd: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> None:
    if meter == "verified_outcomes" and _suppress_verified_meter.get():
        return
    _original_record_usage(
        db,
        tenant_key,
        meter,
        quantity=quantity,
        cost_usd=cost_usd,
        metadata=metadata,
    )


def outcome_fingerprint(row: OutcomeRecord) -> tuple[Any, ...]:
    return (
        row.mission_key,
        row.department_key,
        row.agent_identity,
        row.category,
        row.status,
        row.source_mode,
        round(float(row.quality_score or 0.0), 8),
        int(row.evidence_count or 0),
        round(float(row.baseline_minutes or 0.0), 6),
        round(float(row.actual_minutes or 0.0), 6),
        round(float(row.baseline_cost_usd or 0.0), 6),
        round(float(row.actual_cost_usd or 0.0), 6),
        round(float(row.revenue_value_usd or 0.0), 6),
        round(float(row.sla_target_minutes or 0.0), 6),
        bool(row.sla_met),
        row.result_hash,
        row.metadata_json,
    )


def idempotent_sync_outcomes(db: Session, tenant_key: str) -> dict[str, int]:
    before_rows = list(
        db.scalars(
            select(OutcomeRecord).where(OutcomeRecord.tenant_key == tenant_key)
        ).all()
    )
    before = {
        row.task_key: {
            "fingerprint": outcome_fingerprint(row),
            "updated_at": row.updated_at,
        }
        for row in before_rows
    }

    token = _suppress_verified_meter.set(True)
    try:
        raw = _original_sync_outcomes(db, tenant_key)
    finally:
        _suppress_verified_meter.reset(token)

    after_rows = list(
        db.scalars(
            select(OutcomeRecord).where(OutcomeRecord.tenant_key == tenant_key)
        ).all()
    )
    created = 0
    updated = 0
    unchanged = 0
    for row in after_rows:
        previous = before.get(row.task_key)
        if previous is None:
            created += 1
            continue
        if previous["fingerprint"] != outcome_fingerprint(row):
            updated += 1
            continue
        row.updated_at = previous["updated_at"]
        unchanged += 1

    changed = created + updated
    if changed:
        _original_record_usage(
            db,
            tenant_key,
            "verified_outcomes",
            quantity=changed,
            metadata={
                "source": "evaluation-sync",
                "created": created,
                "updated": updated,
            },
        )
    db.commit()
    return {
        "evaluations": int(raw.get("evaluations", 0)),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "preserved_manual": int(raw.get("preserved_manual", 0)),
    }


def lock_safe_sync_tenant(db: Session, tenant_key: str) -> dict[str, Any]:
    lock_key = f"beezaoffice:business-sync:{tenant_key}"
    owner_token = uuid4().hex
    ttl = max(300, phase13_app.BUSINESS_INTERVAL * 5)
    if not redis_client.set(lock_key, owner_token, nx=True, ex=ttl):
        return {
            "tenant_key": tenant_key,
            "locked": True,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
        }
    try:
        return {
            "tenant_key": tenant_key,
            "locked": False,
            **idempotent_sync_outcomes(db, tenant_key),
        }
    finally:
        with contextlib.suppress(Exception):
            redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                lock_key,
                owner_token,
            )


def period_agent_economics(
    db: Session,
    tenant_key: str,
    rows: list[OutcomeRecord],
) -> list[dict[str, Any]]:
    identities = {
        row.identity_key: row
        for row in db.scalars(
            select(GovernanceIdentity).where(
                GovernanceIdentity.tenant_key == tenant_key
            )
        ).all()
    }
    registry = {
        row.identity_key: row
        for row in db.scalars(
            select(RegisteredAgent)
            .join(
                GovernanceIdentity,
                GovernanceIdentity.identity_key == RegisteredAgent.identity_key,
            )
            .where(GovernanceIdentity.tenant_key == tenant_key)
        ).all()
    }
    grouped: dict[str, list[OutcomeRecord]] = defaultdict(list)
    for row in rows:
        grouped[row.agent_identity or "unassigned"].append(row)

    mission_keys = sorted({row.mission_key for row in rows})
    ledger_cost: dict[str, float] = {}
    if mission_keys:
        ledger_cost = dict(
            db.execute(
                select(BudgetLedger.identity_key, func.sum(BudgetLedger.amount_usd))
                .join(
                    GovernanceIdentity,
                    GovernanceIdentity.identity_key == BudgetLedger.identity_key,
                )
                .where(
                    GovernanceIdentity.tenant_key == tenant_key,
                    BudgetLedger.mission_key.in_(mission_keys),
                    BudgetLedger.entry_type.in_(["CHARGE", "ADJUST"]),
                )
                .group_by(BudgetLedger.identity_key)
            ).all()
        )

    result = []
    for identity_key, group in grouped.items():
        identity = identities.get(identity_key)
        agent = registry.get(identity_key)
        metrics = business_service.executive_metrics(group)
        allocated_cost = float(
            ledger_cost.get(identity_key, metrics["actual_cost_usd"]) or 0.0
        )
        value = float(metrics["value_created_usd"])
        result.append(
            {
                "identity_key": identity_key,
                "name": (
                    identity.display_name
                    if identity
                    else (agent.display_name if agent else identity_key)
                ),
                "department_key": (
                    identity.department_key
                    if identity
                    else (agent.department_key if agent else None)
                ),
                "reliability_score": agent.reliability_score if agent else None,
                "total_runs": agent.total_runs if agent else 0,
                "outcomes": metrics["outcomes"],
                "verified": metrics["verified"],
                "average_quality": metrics["average_quality"],
                "hours_saved": metrics["hours_saved"],
                "cost_usd": round(allocated_cost, 2),
                "value_created_usd": round(value, 2),
                "value_cost_ratio": (
                    round(value / allocated_cost, 4)
                    if allocated_cost > 0
                    else None
                ),
                "sla_compliance": metrics["sla_compliance"],
            }
        )
    return sorted(
        result,
        key=lambda item: (item["value_created_usd"], item["verified"]),
        reverse=True,
    )


business_service.record_usage = hardened_record_usage
business_service.sync_outcomes = idempotent_sync_outcomes
business_service.agent_economics = period_agent_economics
phase13_app.sync_outcomes = idempotent_sync_outcomes
phase13_app.sync_tenant_with_lock = lock_safe_sync_tenant
phase13_app.agent_economics = period_agent_economics
