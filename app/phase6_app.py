from __future__ import annotations

import os
import time
from datetime import timedelta
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import collaboration_service
import main as main_module
import meeting_service
import phase5_app  # noqa: F401 — install Phase 1–5 models, routes, and workers
from governance_models import (
    ApprovalDecisionCreate,
    ApprovalRequest,
    ApprovalRequestCreate,
    AuditRecord,
    BudgetChargeCreate,
    BudgetLedger,
    Department,
    GovernanceIdentity,
    GovernanceRole,
    IdentityCreate,
    KillSwitchUpdate,
    PolicyRule,
    PolicyRuleCreate,
    RoleBinding,
    RoleBindingCreate,
    SystemControl,
    Tenant,
)
from governance_service import (
    DEFAULT_IDENTITY,
    GOVERNANCE_ENFORCED,
    append_audit,
    approval_view,
    audit_view,
    budget_totals,
    create_approval,
    evaluate_authorization,
    execution_enabled,
    get_control,
    identity_view,
    machine_action_allowed,
    mark_approval_used,
    mission_from_path,
    permission_for_request,
    policy_view,
    record_budget_entry,
    request_approval_key,
    request_classification,
    request_estimated_cost,
    request_id,
    request_identity,
    request_risk,
    role_permissions,
    seed_governance,
    verify_audit_chain,
)
from main import (
    AUTH_TOKEN,
    Base,
    SessionLocal,
    app,
    db_session,
    require_token,
    utcnow,
)
from runtime_adapters import RuntimeAdapterError, dispatch_runtime as adapter_dispatch_runtime

app.version = "0.7.0"


def parse_cost(value: str | None) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def infer_service_identity(package: dict[str, Any]) -> str:
    tags = {str(item).lower() for item in package.get("tags") or []}
    if "beeza-meeting" in tags:
        return "service:meeting"
    if "beeza-collaboration" in tags:
        return "service:collaboration"
    return "service:runtime"


async def governed_dispatch(config: Any, package: dict[str, Any]) -> dict[str, Any]:
    identity_key = request_identity.get()
    internal = not request_id.get()
    if internal or identity_key == "service:runtime":
        identity_key = infer_service_identity(package)
    mission_key = str(package.get("mission_key") or "") or None
    decision = machine_action_allowed(identity_key, "runtime:dispatch", mission_key)
    if not decision.get("allowed"):
        if internal:
            with SessionLocal() as db:
                append_audit(
                    db,
                    audit_request_id=f"internal-{uuid4().hex[:16]}",
                    identity_key=identity_key,
                    action="runtime:dispatch",
                    method="INTERNAL",
                    path=f"runtime://{getattr(config, 'key', 'unknown')}/dispatch",
                    resource=mission_key or "",
                    outcome="DENIED",
                    status_code=403,
                    detail={"reason": decision.get("reason"), "package": {"title": package.get("title")}},
                )
                db.commit()
        raise RuntimeAdapterError(str(decision.get("reason") or "Governance denied runtime dispatch"))

    started = time.perf_counter()
    try:
        result = await adapter_dispatch_runtime(config, package)
        if internal:
            with SessionLocal() as db:
                append_audit(
                    db,
                    audit_request_id=f"internal-{uuid4().hex[:16]}",
                    identity_key=identity_key,
                    action="runtime:dispatch",
                    method="INTERNAL",
                    path=f"runtime://{getattr(config, 'key', 'unknown')}/dispatch",
                    resource=mission_key or "",
                    outcome="ALLOWED",
                    status_code=202,
                    detail={
                        "runtime": getattr(config, "key", "unknown"),
                        "title": str(package.get("title") or "")[:240],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "remote_id": result.get("remote_id"),
                        "status": result.get("status"),
                    },
                )
                db.commit()
        return result
    except Exception as exc:
        if internal:
            with SessionLocal() as db:
                append_audit(
                    db,
                    audit_request_id=f"internal-{uuid4().hex[:16]}",
                    identity_key=identity_key,
                    action="runtime:dispatch",
                    method="INTERNAL",
                    path=f"runtime://{getattr(config, 'key', 'unknown')}/dispatch",
                    resource=mission_key or "",
                    outcome="ERROR",
                    status_code=502,
                    detail={"error": str(exc)[:1000]},
                )
                db.commit()
        raise


# Install the governance guard at the shared dispatch boundary. Existing routes and
# background workers resolve these module globals at runtime, so all four adapters
# pass through the same policy and kill-switch check.
main_module.dispatch_runtime = governed_dispatch
collaboration_service.dispatch_runtime = governed_dispatch
meeting_service.dispatch_runtime = governed_dispatch


@app.middleware("http")
async def governance_middleware(request: Request, call_next: Callable):
    path = request.url.path
    method = request.method.upper()
    if not path.startswith("/api/"):
        return await call_next(request)

    identity_key = request.headers.get("X-Beeza-Identity", DEFAULT_IDENTITY).strip() or DEFAULT_IDENTITY
    action = permission_for_request(method, path)
    risk_level = request.headers.get("X-Beeza-Risk-Level", "NORMAL").upper()
    classification = request.headers.get("X-Beeza-Data-Classification", "INTERNAL").upper()
    approval_key = request.headers.get("X-Beeza-Approval-Key", "").strip()
    estimated_cost = parse_cost(request.headers.get("X-Beeza-Estimated-Cost-USD"))
    req_id = request.headers.get("X-Request-ID", f"REQ-{uuid4().hex[:16].upper()}")
    mission_key = mission_from_path(path)
    source_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("User-Agent", "")
    mutating = method in {"POST", "PUT", "PATCH", "DELETE"}

    identity_token = request_identity.set(identity_key)
    request_id_token = request_id.set(req_id)
    risk_token = request_risk.set(risk_level)
    classification_token = request_classification.set(classification)
    approval_token = request_approval_key.set(approval_key)
    cost_token = request_estimated_cost.set(estimated_cost)
    started = time.perf_counter()
    approved_for_use: str | None = None

    try:
        if mutating and AUTH_TOKEN and request.headers.get("Authorization") != f"Bearer {AUTH_TOKEN}":
            with SessionLocal() as db:
                append_audit(
                    db,
                    audit_request_id=req_id,
                    identity_key=identity_key,
                    action=action,
                    method=method,
                    path=path,
                    resource=mission_key or "",
                    outcome="DENIED",
                    status_code=401,
                    detail={"reason": "Invalid BeezaOffice token"},
                    source_ip=source_ip,
                    user_agent=user_agent,
                )
                db.commit()
            return JSONResponse(status_code=401, content={"detail": "Invalid BeezaOffice token", "request_id": req_id})

        if mutating:
            with SessionLocal() as db:
                decision = evaluate_authorization(
                    db,
                    identity_key=identity_key,
                    action=action,
                    mission_key=mission_key,
                    risk_level=risk_level,
                    data_classification=classification,
                    estimated_cost_usd=estimated_cost,
                    approval_key=approval_key,
                )
                if not decision.get("allowed"):
                    response_status = 403
                    detail: dict[str, Any] = {
                        "reason": decision.get("reason"),
                        "action": action,
                        "identity": identity_key,
                        "request_id": req_id,
                    }
                    if decision.get("approval_required"):
                        response_status = 428
                        pending = db.scalar(
                            select(ApprovalRequest).where(
                                ApprovalRequest.requester_identity == identity_key,
                                ApprovalRequest.action == action,
                                ApprovalRequest.target == path,
                                ApprovalRequest.status == "PENDING",
                                ApprovalRequest.expires_at > utcnow(),
                            ).order_by(ApprovalRequest.requested_at.desc())
                        )
                        if pending is None:
                            pending = create_approval(
                                db,
                                action=action,
                                requester_identity=identity_key,
                                target=path,
                                mission_key=mission_key,
                                risk_level=risk_level,
                                reason=f"Governance approval required for {action} at {path}",
                            )
                        detail["approval"] = approval_view(pending)
                    append_audit(
                        db,
                        audit_request_id=req_id,
                        identity_key=identity_key,
                        action=action,
                        method=method,
                        path=path,
                        resource=mission_key or "",
                        outcome="DENIED",
                        status_code=response_status,
                        detail=detail,
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )
                    db.commit()
                    return JSONResponse(status_code=response_status, content={"detail": detail})
                approved_for_use = decision.get("approval_key")

        try:
            response = await call_next(request)
        except Exception as exc:
            if mutating:
                with SessionLocal() as db:
                    append_audit(
                        db,
                        audit_request_id=req_id,
                        identity_key=identity_key,
                        action=action,
                        method=method,
                        path=path,
                        resource=mission_key or "",
                        outcome="ERROR",
                        status_code=500,
                        detail={
                            "error": str(exc)[:1200],
                            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        },
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )
                    db.commit()
            raise

        if mutating:
            with SessionLocal() as db:
                if response.status_code < 400:
                    mark_approval_used(db, approved_for_use)
                    if estimated_cost > 0:
                        record_budget_entry(
                            db,
                            identity_key=identity_key,
                            mission_key=mission_key,
                            action=action,
                            amount_usd=estimated_cost,
                            entry_type="RESERVE",
                            reference_key=req_id,
                            details={"path": path, "risk_level": risk_level},
                            created_by=identity_key,
                        )
                append_audit(
                    db,
                    audit_request_id=req_id,
                    identity_key=identity_key,
                    action=action,
                    method=method,
                    path=path,
                    resource=mission_key or "",
                    outcome="ALLOWED" if response.status_code < 400 else "ERROR",
                    status_code=response.status_code,
                    detail={
                        "risk_level": risk_level,
                        "classification": classification,
                        "estimated_cost_usd": estimated_cost,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                    source_ip=source_ip,
                    user_agent=user_agent,
                )
                db.commit()
        response.headers["X-Beeza-Request-ID"] = req_id
        return response
    finally:
        request_identity.reset(identity_token)
        request_id.reset(request_id_token)
        request_risk.reset(risk_token)
        request_classification.reset(classification_token)
        request_approval_key.reset(approval_token)
        request_estimated_cost.reset(cost_token)


@app.on_event("startup")
def startup_governance() -> None:
    # Main startup creates all metadata after Phase 6 imports have registered the
    # governance models. This second startup hook only seeds policy data.
    with SessionLocal() as db:
        seed_governance(db)


def require_governance(permission: str):
    def dependency(
        authorization: str | None = Header(default=None),
        x_beeza_identity: str | None = Header(default=None),
        db: Session = Depends(db_session),
    ) -> str:
        require_token(authorization)
        identity_key = (x_beeza_identity or DEFAULT_IDENTITY).strip() or DEFAULT_IDENTITY
        decision = evaluate_authorization(
            db,
            identity_key=identity_key,
            action=permission,
            risk_level="NORMAL",
            data_classification="INTERNAL",
        )
        if not decision.get("allowed"):
            raise HTTPException(status_code=403, detail=decision.get("reason"))
        return identity_key

    return dependency


@app.get("/api/governance/context")
def governance_context(
    identity_key: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == identity_key)
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Governance identity not found")
    control = get_control(db)
    pending = db.scalar(
        select(ApprovalRequest.id).where(ApprovalRequest.status == "PENDING").limit(1)
    )
    return {
        "enforced": GOVERNANCE_ENFORCED,
        "default_identity": DEFAULT_IDENTITY,
        "identity": identity_view(identity, role_permissions(db, identity_key)),
        "execution": {
            "enabled": execution_enabled(db),
            "reason": control.reason if control else "",
            "changed_by": control.changed_by if control else None,
            "updated_at": control.updated_at.isoformat() if control else None,
        },
        "budget": {
            **budget_totals(db, identity_key),
            "daily_limit": identity.daily_budget_usd,
            "monthly_limit": identity.monthly_budget_usd,
        },
        "pending_approvals": 1 if pending else 0,
    }


@app.get("/api/governance/identities")
def list_governance_identities(
    status: str | None = Query(default=None),
    identity_type: str | None = Query(default=None),
    _: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(GovernanceIdentity)
    if status:
        statement = statement.where(GovernanceIdentity.status == status.upper())
    if identity_type:
        statement = statement.where(GovernanceIdentity.identity_type == identity_type.upper())
    rows = db.scalars(statement.order_by(GovernanceIdentity.identity_type, GovernanceIdentity.display_name)).all()
    return [identity_view(row, role_permissions(db, row.identity_key)) for row in rows]


@app.post("/api/governance/identities", status_code=201)
def create_governance_identity(
    payload: IdentityCreate,
    actor: str = Depends(require_governance("governance:identity:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if db.scalar(select(GovernanceIdentity.id).where(GovernanceIdentity.identity_key == payload.identity_key)):
        raise HTTPException(status_code=409, detail="Identity already exists")
    if db.scalar(select(Tenant.id).where(Tenant.tenant_key == payload.tenant_key)) is None:
        raise HTTPException(status_code=409, detail="Tenant not found")
    if payload.department_key and db.scalar(
        select(Department.id).where(Department.department_key == payload.department_key)
    ) is None:
        raise HTTPException(status_code=409, detail="Department not found")
    now = utcnow()
    row = GovernanceIdentity(
        identity_key=payload.identity_key,
        tenant_key=payload.tenant_key,
        identity_type=payload.identity_type,
        display_name=payload.display_name,
        department_key=payload.department_key,
        status="ACTIVE",
        clearance=payload.clearance,
        daily_budget_usd=payload.daily_budget_usd,
        monthly_budget_usd=payload.monthly_budget_usd,
        attributes={**payload.attributes, "created_by": actor},
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return identity_view(row, [])


@app.get("/api/governance/roles")
def list_governance_roles(
    _: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(GovernanceRole).order_by(GovernanceRole.name)).all()
    return [
        {
            "key": row.role_key,
            "name": row.name,
            "description": row.description,
            "permissions": row.permissions,
            "system_role": row.system_role,
        }
        for row in rows
    ]


@app.post("/api/governance/bindings", status_code=201)
def create_role_binding(
    payload: RoleBindingCreate,
    actor: str = Depends(require_governance("governance:role:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if db.scalar(select(GovernanceIdentity.id).where(GovernanceIdentity.identity_key == payload.identity_key)) is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    if db.scalar(select(GovernanceRole.id).where(GovernanceRole.role_key == payload.role_key)) is None:
        raise HTTPException(status_code=404, detail="Role not found")
    existing = db.scalar(
        select(RoleBinding).where(
            RoleBinding.identity_key == payload.identity_key,
            RoleBinding.role_key == payload.role_key,
            RoleBinding.scope_type == payload.scope_type,
            RoleBinding.scope_key == payload.scope_key,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Role binding already exists")
    row = RoleBinding(
        binding_key=f"BIND-{uuid4().hex[:14].upper()}",
        identity_key=payload.identity_key,
        role_key=payload.role_key,
        scope_type=payload.scope_type,
        scope_key=payload.scope_key,
        created_by=actor,
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    return {
        "key": row.binding_key,
        "identity_key": row.identity_key,
        "role_key": row.role_key,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
    }


@app.get("/api/governance/policies")
def list_policies(
    _: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(PolicyRule).order_by(PolicyRule.priority, PolicyRule.name)).all()
    return [policy_view(row) for row in rows]


@app.post("/api/governance/policies", status_code=201)
def create_policy(
    payload: PolicyRuleCreate,
    actor: str = Depends(require_governance("governance:policy:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    now = utcnow()
    row = PolicyRule(
        policy_key=f"POL-{uuid4().hex[:14].upper()}",
        name=payload.name,
        action_pattern=payload.action_pattern,
        effect=payload.effect,
        risk_levels=[item.upper() for item in payload.risk_levels],
        minimum_clearance=payload.minimum_clearance,
        maximum_cost_usd=payload.maximum_cost_usd,
        priority=payload.priority,
        enabled=True,
        conditions=payload.conditions,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return policy_view(row)


@app.get("/api/governance/approvals")
def list_approvals(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(ApprovalRequest)
    if status:
        statement = statement.where(ApprovalRequest.status == status.upper())
    rows = db.scalars(statement.order_by(ApprovalRequest.requested_at.desc()).limit(limit)).all()
    return [approval_view(row) for row in rows]


@app.post("/api/governance/approvals", status_code=201)
def request_governance_approval(
    payload: ApprovalRequestCreate,
    actor: str = Depends(require_governance("approval:request")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = create_approval(
        db,
        action=payload.action,
        requester_identity=actor,
        target=payload.target,
        mission_key=payload.mission_key,
        risk_level=payload.risk_level,
        reason=payload.reason,
        payload_hash=payload.payload_hash,
        expires_in_minutes=payload.expires_in_minutes,
    )
    db.commit()
    db.refresh(row)
    return approval_view(row)


@app.post("/api/governance/approvals/{approval_key}/decision")
def decide_governance_approval(
    approval_key: str,
    payload: ApprovalDecisionCreate,
    actor: str = Depends(require_governance("approval:decide")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.approval_key == approval_key)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if row.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Approval is already {row.status}")
    if row.expires_at <= utcnow():
        row.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=409, detail="Approval request expired")
    if actor == row.requester_identity:
        raise HTTPException(status_code=409, detail="Requester cannot approve their own request")
    row.status = payload.decision
    row.decided_by = actor
    row.decision_note = payload.note
    row.decided_at = utcnow()
    db.commit()
    db.refresh(row)
    return approval_view(row)


@app.get("/api/governance/controls")
def list_controls(
    _: str = Depends(require_governance("governance:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(SystemControl).order_by(SystemControl.control_key)).all()
    return [
        {
            "key": row.control_key,
            "enabled": row.enabled,
            "reason": row.reason,
            "changed_by": row.changed_by,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


@app.post("/api/governance/kill-switch")
def update_kill_switch(
    payload: KillSwitchUpdate,
    actor: str = Depends(require_governance("governance:kill-switch")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = get_control(db)
    if row is None:
        row = SystemControl(
            control_key="runtime_execution_enabled",
            enabled=payload.execution_enabled,
            reason=payload.reason,
            changed_by=actor,
            updated_at=utcnow(),
        )
        db.add(row)
    else:
        row.enabled = payload.execution_enabled
        row.reason = payload.reason
        row.changed_by = actor
        row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return {
        "key": row.control_key,
        "enabled": row.enabled,
        "reason": row.reason,
        "changed_by": row.changed_by,
        "updated_at": row.updated_at.isoformat(),
    }


@app.get("/api/governance/budget")
def read_budget(
    identity_key: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: str = Depends(require_governance("budget:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    target = identity_key or actor
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == target)
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    rows = db.scalars(
        select(BudgetLedger)
        .where(BudgetLedger.identity_key == target)
        .order_by(BudgetLedger.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "identity": identity_view(identity, role_permissions(db, target)),
        "totals": budget_totals(db, target),
        "entries": [
            {
                "key": row.ledger_key,
                "mission_key": row.mission_key,
                "action": row.action,
                "entry_type": row.entry_type,
                "amount_usd": row.amount_usd,
                "reference_key": row.reference_key,
                "details": row.details,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@app.post("/api/governance/budget/charge", status_code=201)
def charge_budget(
    payload: BudgetChargeCreate,
    actor: str = Depends(require_governance("budget:charge")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == payload.identity_key
        )
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    totals = budget_totals(db, payload.identity_key)
    if totals["daily"] + payload.amount_usd > identity.daily_budget_usd:
        raise HTTPException(status_code=409, detail="Daily budget limit exceeded")
    if totals["monthly"] + payload.amount_usd > identity.monthly_budget_usd:
        raise HTTPException(status_code=409, detail="Monthly budget limit exceeded")
    row = record_budget_entry(
        db,
        identity_key=payload.identity_key,
        mission_key=payload.mission_key,
        action=payload.action,
        amount_usd=payload.amount_usd,
        entry_type="CHARGE",
        reference_key=payload.reference_key,
        details=payload.details,
        created_by=actor,
    )
    db.commit()
    return {
        "key": row.ledger_key,
        "identity_key": row.identity_key,
        "amount_usd": row.amount_usd,
        "entry_type": row.entry_type,
        "created_at": row.created_at.isoformat(),
    }


@app.get("/api/governance/audit")
def list_audit_records(
    identity_key: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("audit:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(AuditRecord)
    if identity_key:
        statement = statement.where(AuditRecord.identity_key == identity_key)
    if outcome:
        statement = statement.where(AuditRecord.outcome == outcome.upper())
    rows = db.scalars(statement.order_by(AuditRecord.id.desc()).limit(limit)).all()
    return [audit_view(row) for row in rows]


@app.get("/api/governance/audit/verify")
def verify_governance_audit(
    limit: int = Query(default=5000, ge=1, le=50_000),
    _: str = Depends(require_governance("audit:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return verify_audit_chain(db, limit)
