from __future__ import annotations

import re
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase11_app  # noqa: F401 — install Phase 1–11 protocol gateway
from governance_models import ApprovalRequest
from governance_service import (
    append_audit,
    approval_view,
    create_approval,
    evaluate_authorization,
    has_permission,
    mark_approval_used,
    record_budget_entry,
)
from main import Agent, RuntimeConnector, app, db_session, engine, redis_client, utcnow
from protocol_models import ProtocolTask
from registry_models import RegisteredAgent
from sop_models import SOPRun, SOPTemplate

app.version = "0.12.0"
_TASK_PATH = re.compile(r"^/tasks/([^/:]+)(?::subscribe|:cancel)?$")
_EXTERNAL_EXECUTION_PATHS = [
    re.compile(r"^/message:send$"),
    re.compile(r"^/v1/chat/completions$"),
    re.compile(r"^/tasks/[^/:]+:cancel$"),
    re.compile(r"^/hooks/[^/]+$"),
]


def parse_cost(value: str | None) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


@app.middleware("http")
async def protocol_task_scope_middleware(request: Request, call_next: Callable):
    match = _TASK_PATH.match(request.url.path)
    if match and request.method.upper() in {"GET", "POST"}:
        task_id = match.group(1)
        actor = request.headers.get("X-Beeza-Identity", "service:protocol").strip() or "service:protocol"
        with phase11_app.SessionLocal() as db:
            row = db.scalar(select(ProtocolTask).where(ProtocolTask.task_id == task_id))
            if row is not None and row.client_identity != actor and not has_permission(db, actor, "protocol:operate"):
                return JSONResponse(status_code=404, content={"detail": "Protocol task not found"})
    return await call_next(request)


@app.middleware("http")
async def external_protocol_governance(request: Request, call_next: Callable):
    path = request.url.path
    if request.method.upper() != "POST" or not any(pattern.match(path) for pattern in _EXTERNAL_EXECUTION_PATHS):
        return await call_next(request)

    actor = request.headers.get("X-Beeza-Identity", "service:protocol").strip() or "service:protocol"
    risk = request.headers.get("X-Beeza-Risk-Level", "NORMAL").upper()
    classification = request.headers.get("X-Beeza-Data-Classification", "INTERNAL").upper()
    approval_key = request.headers.get("X-Beeza-Approval-Key", "").strip()
    estimated_cost = parse_cost(request.headers.get("X-Beeza-Estimated-Cost-USD"))
    req_id = request.headers.get("X-Request-ID", f"REQ-{uuid4().hex[:16].upper()}")
    source_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("User-Agent", "")
    action = "protocol:use"
    started = time.perf_counter()
    approved_for_use: str | None = None

    with phase11_app.SessionLocal() as db:
        decision = evaluate_authorization(
            db,
            identity_key=actor,
            action=action,
            mission_key=None,
            risk_level=risk,
            data_classification=classification,
            estimated_cost_usd=estimated_cost,
            approval_key=approval_key,
        )
        if not decision.get("allowed"):
            status = 403
            detail: dict[str, Any] = {
                "reason": decision.get("reason"),
                "action": action,
                "identity": actor,
                "request_id": req_id,
            }
            if decision.get("approval_required"):
                status = 428
                pending = db.scalar(
                    select(ApprovalRequest).where(
                        ApprovalRequest.requester_identity == actor,
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
                        requester_identity=actor,
                        target=path,
                        mission_key=None,
                        risk_level=risk,
                        reason=f"Governance approval required for external protocol execution at {path}",
                    )
                detail["approval"] = approval_view(pending)
            append_audit(
                db,
                audit_request_id=req_id,
                identity_key=actor,
                action=action,
                method="POST",
                path=path,
                resource="protocol-gateway",
                outcome="DENIED",
                status_code=status,
                detail=detail,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            db.commit()
            return JSONResponse(status_code=status, content={"detail": detail})
        approved_for_use = decision.get("approval_key")

    try:
        response = await call_next(request)
    except Exception as exc:
        with phase11_app.SessionLocal() as db:
            append_audit(
                db,
                audit_request_id=req_id,
                identity_key=actor,
                action=action,
                method="POST",
                path=path,
                resource="protocol-gateway",
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

    with phase11_app.SessionLocal() as db:
        if response.status_code < 400:
            mark_approval_used(db, approved_for_use)
            if estimated_cost > 0:
                record_budget_entry(
                    db,
                    identity_key=actor,
                    mission_key=None,
                    action=action,
                    amount_usd=estimated_cost,
                    entry_type="RESERVE",
                    reference_key=req_id,
                    details={"path": path, "risk_level": risk},
                    created_by=actor,
                )
        append_audit(
            db,
            audit_request_id=req_id,
            identity_key=actor,
            action=action,
            method="POST",
            path=path,
            resource="protocol-gateway",
            outcome="ALLOWED" if response.status_code < 400 else "ERROR",
            status_code=response.status_code,
            detail={
                "risk_level": risk,
                "classification": classification,
                "estimated_cost_usd": estimated_cost,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
            source_ip=source_ip,
            user_agent=user_agent,
        )
        db.commit()
    return response


app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/health"
        and "GET" in getattr(route, "methods", set())
    )
]


@app.get("/api/health")
def protocol_health(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    database = "ok"
    queue = "ok"
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        database = "error"
    try:
        redis_client.ping()
    except Exception:
        queue = "error"

    runtimes = list(
        db.scalars(select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)).all()
    )
    has_registry = db.scalar(select(RegisteredAgent.id).limit(1)) is not None
    registered_agents = db.query(RegisteredAgent).count() if has_registry else db.query(Agent).count()
    active_agents = (
        db.query(RegisteredAgent).filter(RegisteredAgent.status == "ACTIVE").count()
        if has_registry else registered_agents
    )
    protocol_tasks = db.query(ProtocolTask).count()
    active_protocol_tasks = db.query(ProtocolTask).filter(
        ProtocolTask.state.not_in(phase11_app.TERMINAL_PROTOCOL_STATES)
    ).count()
    worker = redis_client.hgetall("beezaoffice:protocol-worker")
    return {
        "status": "ok" if database == queue == "ok" else "degraded",
        "database": database,
        "queue": queue,
        "registered_agents": registered_agents,
        "active_agents": active_agents,
        "registry_scale_target": 1000,
        "runtime_connectors": len(runtimes),
        "runtime_online": sum(row.status == "ONLINE" for row in runtimes),
        "runtime_configured": sum(bool(row.base_url) for row in runtimes),
        "sop_templates": db.query(SOPTemplate).count(),
        "active_sop_runs": db.query(SOPRun).filter(
            SOPRun.status.in_(["PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK"])
        ).count(),
        "protocol_tasks": protocol_tasks,
        "active_protocol_tasks": active_protocol_tasks,
        "protocol_worker": worker.get("status", "starting"),
        "protocols": ["a2a-1.0", "mcp-2025-06-18", "openai-chat", "webhook", "sse"],
        "governance": "enforced",
        "phase": 11,
    }
