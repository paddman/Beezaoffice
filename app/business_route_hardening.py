from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase13_app
from business_models import OutcomeRecord, OutcomeUpsert
from business_service import outcome_view, record_usage
from collaboration_models import CollaborationTask
from enterprise_service import DEFAULT_TENANT, resource_tenant
from main import app, db_session, utcnow
from phase6_app import require_governance
from phase12_app import tenant_header


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


remove_route("/api/business/outcomes", "POST")


@app.post("/api/business/outcomes", status_code=201)
def upsert_manual_outcome_hardened(
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
    previous_status = row.status if row else None
    previous_hash = row.result_hash if row else None
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
        "sla_met": (
            payload.sla_target_minutes > 0
            and payload.actual_minutes <= payload.sla_target_minutes
        ),
        "result_hash": payload.result_hash,
        "assumptions": {"estimated": False, "entered_by": actor},
        "metadata_json": payload.metadata,
        "verified_at": now,
        "updated_at": now,
    }
    created = row is None
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

    newly_verified = payload.status == "VERIFIED" and (
        created
        or previous_status != "VERIFIED"
        or (payload.result_hash and payload.result_hash != previous_hash)
    )
    if newly_verified:
        record_usage(
            db,
            tenant_key,
            "verified_outcomes",
            quantity=1,
            metadata={
                "source": "manual",
                "task_key": payload.task_key,
                "mission_key": payload.mission_key,
            },
        )
    db.commit()
    db.refresh(row)
    return {**outcome_view(row), "created": created, "metered": newly_verified}


phase13_app.upsert_manual_outcome = upsert_manual_outcome_hardened
