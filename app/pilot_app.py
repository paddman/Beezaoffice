from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase14_bootstrap  # noqa: F401 — install Phase 1–14 commercial runtime
from enterprise_models import EnterpriseTenant
from governance_models import GovernanceRole
from main import SessionLocal, app, db_session, utcnow
from phase6_app import require_governance
from phase12_app import tenant_header
from pilot_models import (
    PILOT_GATES,
    PilotDecision,
    PilotGateUpsert,
    PilotProgram,
    PilotProgramCreate,
    gate_view,
    pilot_view,
)
from pilot_service import (
    DEFAULT_ACCEPTANCE_CRITERIA,
    gates_for,
    readiness_view,
    reconcile_pilot,
    seed_pilot,
    upsert_gate,
)
from release_version import APP_VERSION, RELEASE_CHANNEL, RELEASE_NAME, RELEASE_TAG

app.version = APP_VERSION

_RULES = [
    ("POST", re.compile(r"^/api/pilot/programs$"), "pilot:manage"),
    ("POST", re.compile(r"^/api/pilot/programs/[^/]+/gates$"), "pilot:evidence"),
    ("POST", re.compile(r"^/api/pilot/programs/[^/]+/decision$"), "pilot:accept"),
]
for rule in reversed(_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.update({"pilot:manage", "pilot:evidence", "pilot:accept"})


def ensure_pilot_permissions(db: Session) -> None:
    additions = {
        "role:executive": {"pilot:read", "pilot:manage", "pilot:evidence", "pilot:accept"},
        "role:manager": {"pilot:read", "pilot:manage", "pilot:evidence"},
        "role:operator": {"pilot:read", "pilot:evidence"},
        "role:auditor": {"pilot:read"},
        "role:service": {"pilot:read", "pilot:evidence"},
        "role:agent": {"pilot:read"},
        "role:runtime": {"pilot:read"},
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
def start_pilot_operations() -> None:
    with SessionLocal() as db:
        ensure_pilot_permissions(db)
        seed_pilot(db)


def get_program(db: Session, tenant_key: str, pilot_key: str) -> PilotProgram:
    row = db.scalar(
        select(PilotProgram).where(
            PilotProgram.pilot_key == pilot_key,
            PilotProgram.tenant_key == tenant_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Pilot program not found")
    return row


@app.get("/api/pilot/checklist")
def pilot_checklist(
    _: str = Depends(require_governance("pilot:read")),
) -> dict[str, Any]:
    return {
        "version": APP_VERSION,
        "release_name": RELEASE_NAME,
        "release_tag": RELEASE_TAG,
        "release_channel": RELEASE_CHANNEL,
        "required_gates": PILOT_GATES,
        "default_acceptance_criteria": DEFAULT_ACCEPTANCE_CRITERIA,
    }


@app.get("/api/pilot/status")
def pilot_status(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("pilot:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(PilotProgram)
            .where(PilotProgram.tenant_key == tenant_key)
            .order_by(PilotProgram.created_at.desc())
        ).all()
    )
    programs = [readiness_view(db, row) for row in rows]
    current = programs[0] if programs else None
    return {
        "version": APP_VERSION,
        "release": {
            "name": RELEASE_NAME,
            "tag": RELEASE_TAG,
            "channel": RELEASE_CHANNEL,
        },
        "tenant_key": tenant_key,
        "current": current,
        "programs": programs,
        "production_promotion_allowed": bool(
            current and current["summary"]["accepted"]
        ),
    }


@app.get("/api/pilot/programs")
def list_pilot_programs(
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("pilot:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(PilotProgram)
        .where(PilotProgram.tenant_key == tenant_key)
        .order_by(PilotProgram.created_at.desc())
    ).all()
    return [readiness_view(db, row) for row in rows]


@app.post("/api/pilot/programs", status_code=201)
def create_pilot_program(
    payload: PilotProgramCreate,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("pilot:manage")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    tenant = db.scalar(
        select(EnterpriseTenant).where(EnterpriseTenant.tenant_key == tenant_key)
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    existing = db.scalar(
        select(PilotProgram).where(
            PilotProgram.tenant_key == tenant_key,
            PilotProgram.target_version == payload.target_version,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A pilot program already exists for this Tenant and version",
        )
    now = utcnow()
    row = PilotProgram(
        pilot_key=f"PILOT-{uuid4().hex[:16].upper()}",
        tenant_key=tenant_key,
        customer_name=payload.customer_name,
        environment=payload.environment,
        target_version=payload.target_version,
        status="READY",
        owner_identity=actor,
        runtime_keys=sorted(set(payload.runtime_keys)),
        acceptance_criteria={
            **DEFAULT_ACCEPTANCE_CRITERIA,
            **payload.acceptance_criteria,
        },
        notes=payload.notes,
        accepted_by=None,
        accepted_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    for gate_key in PILOT_GATES:
        upsert_gate(
            db,
            row,
            gate_key,
            "PENDING",
            "SYSTEM",
            "Awaiting evidence",
            {},
            "",
            actor,
            None,
            None,
        )
    return readiness_view(db, row)


@app.get("/api/pilot/programs/{pilot_key}")
def read_pilot_program(
    pilot_key: str,
    tenant_key: str = Depends(tenant_header),
    _: str = Depends(require_governance("pilot:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return readiness_view(db, get_program(db, tenant_key, pilot_key))


@app.post("/api/pilot/programs/{pilot_key}/gates")
def record_pilot_gate(
    pilot_key: str,
    payload: PilotGateUpsert,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("pilot:evidence")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = get_program(db, tenant_key, pilot_key)
    try:
        evidence = upsert_gate(
            db,
            row,
            payload.gate_key,
            payload.status,
            payload.source,
            payload.summary,
            payload.metrics,
            payload.artifact_ref,
            actor,
            payload.started_at,
            payload.completed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "evidence": gate_view(evidence),
        "readiness": readiness_view(db, row),
    }


@app.post("/api/pilot/programs/{pilot_key}/decision")
def decide_pilot(
    pilot_key: str,
    payload: PilotDecision,
    tenant_key: str = Depends(tenant_header),
    actor: str = Depends(require_governance("pilot:accept")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = get_program(db, tenant_key, pilot_key)
    row = reconcile_pilot(db, row)
    now = utcnow()
    if payload.decision == "ACCEPT":
        if row.status != "AWAITING_ACCEPTANCE":
            pending = [
                gate.gate_key
                for gate in gates_for(db, row.pilot_key)
                if gate.gate_key in PILOT_GATES and gate.status != "PASS"
            ]
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "All required pilot gates must pass before acceptance",
                    "incomplete_gates": pending,
                },
            )
        row.status = "ACCEPTED"
        row.accepted_by = actor
        row.accepted_at = now
    elif payload.decision == "REJECT":
        row.status = "REJECTED"
        row.accepted_by = actor
        row.accepted_at = now
    elif payload.decision == "PAUSE":
        row.status = "BLOCKED"
        row.accepted_by = None
        row.accepted_at = None
    else:
        row.status = "RUNNING"
        row.accepted_by = None
        row.accepted_at = None
    if payload.note:
        row.notes = f"{row.notes}\n[{now.isoformat()}] {actor}: {payload.note}".strip()
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return readiness_view(db, row)
