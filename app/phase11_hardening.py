from __future__ import annotations

import json
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import phase11_app
import phase11_security  # noqa: F401 — install protocol runtime and MCP transport checks
import protocol_service
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
from main import AUTH_TOKEN, RuntimeConnector, SessionLocal, app, db_session, utcnow
from protocol_models import ProtocolTask

_ALLOWED_PRIORITIES = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
_ALLOWED_CLEARANCES = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
_EXECUTION_MCP_TOOLS = {"beeza_create_task", "beeza_run_sop"}
_original_create_protocol_task = protocol_service.create_protocol_task
_original_mcp_gateway = phase11_app.mcp_gateway


def parse_cost(value: str | None) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


async def hardened_create_protocol_task(
    db: Session,
    *,
    protocol: str,
    client_identity: str,
    message_id: str,
    context_id: str,
    text: str,
    title: str | None = None,
    priority: str = "NORMAL",
    required_skills: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    required_tools: list[str] | None = None,
    required_clearance: str = "INTERNAL",
    preferred_runtime_key: str | None = None,
    fixed_runtime: bool = False,
    metadata: dict[str, Any] | None = None,
):
    normalized_priority = str(priority or "NORMAL").upper()
    normalized_clearance = str(required_clearance or "INTERNAL").upper()
    if normalized_priority not in _ALLOWED_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"Unsupported priority {priority}")
    if normalized_clearance not in _ALLOWED_CLEARANCES:
        raise HTTPException(status_code=422, detail=f"Unsupported data clearance {required_clearance}")

    runtime_key = str(preferred_runtime_key or "").strip().lower() or None
    if fixed_runtime and not runtime_key:
        raise HTTPException(status_code=422, detail="Fixed runtime routing requires preferred_runtime_key")
    if runtime_key:
        runtime = db.scalar(
            select(RuntimeConnector).where(RuntimeConnector.runtime_key == runtime_key)
        )
        if runtime is None:
            raise HTTPException(status_code=422, detail=f"Unknown runtime {runtime_key}")

    return await _original_create_protocol_task(
        db,
        protocol=str(protocol).strip().lower()[:40],
        client_identity=client_identity,
        message_id=message_id,
        context_id=context_id,
        text=text,
        title=title,
        priority=normalized_priority,
        required_skills=sorted({str(item).strip() for item in required_skills or [] if str(item).strip()}),
        required_capabilities=sorted({str(item).strip() for item in required_capabilities or [] if str(item).strip()}),
        required_tools=sorted({str(item).strip() for item in required_tools or [] if str(item).strip()}),
        required_clearance=normalized_clearance,
        preferred_runtime_key=runtime_key,
        fixed_runtime=fixed_runtime,
        metadata=metadata,
    )


protocol_service.create_protocol_task = hardened_create_protocol_task
phase11_app.create_protocol_task = hardened_create_protocol_task


async def mcp_execution_request(request: Request) -> bool:
    if request.method.upper() != "POST" or request.url.path != "/mcp":
        return False
    try:
        payload = await request.json()
    except Exception:
        return False
    if not isinstance(payload, dict) or payload.get("method") != "tools/call":
        return False
    params = payload.get("params") or {}
    return str(params.get("name") or "") in _EXECUTION_MCP_TOOLS


@app.middleware("http")
async def governed_mcp_execution(request: Request, call_next: Callable):
    if not await mcp_execution_request(request):
        return await call_next(request)

    if AUTH_TOKEN and request.headers.get("Authorization") != f"Bearer {AUTH_TOKEN}":
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

    with SessionLocal() as db:
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
                        ApprovalRequest.target == "/mcp",
                        ApprovalRequest.status == "PENDING",
                        ApprovalRequest.expires_at > utcnow(),
                    ).order_by(ApprovalRequest.requested_at.desc())
                )
                if pending is None:
                    pending = create_approval(
                        db,
                        action=action,
                        requester_identity=actor,
                        target="/mcp",
                        mission_key=None,
                        risk_level=risk,
                        reason="Governance approval required for MCP execution tool call",
                    )
                detail["approval"] = approval_view(pending)
            append_audit(
                db,
                audit_request_id=req_id,
                identity_key=actor,
                action=action,
                method="POST",
                path="/mcp",
                resource="mcp-execution-tool",
                outcome="DENIED",
                status_code=status,
                detail=detail,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            db.commit()
            return JSONResponse(
                status_code=status,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32003, "message": "Governance denied MCP execution", "data": detail},
                },
            )
        approved_for_use = decision.get("approval_key")

    try:
        response = await call_next(request)
    except Exception as exc:
        with SessionLocal() as db:
            append_audit(
                db,
                audit_request_id=req_id,
                identity_key=actor,
                action=action,
                method="POST",
                path="/mcp",
                resource="mcp-execution-tool",
                outcome="ERROR",
                status_code=500,
                detail={"error": str(exc)[:1200]},
                source_ip=source_ip,
                user_agent=user_agent,
            )
            db.commit()
        raise

    with SessionLocal() as db:
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
                    details={"path": "/mcp", "risk_level": risk},
                    created_by=actor,
                )
        append_audit(
            db,
            audit_request_id=req_id,
            identity_key=actor,
            action=action,
            method="POST",
            path="/mcp",
            resource="mcp-execution-tool",
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


# Replace MCP route with an ownership-aware wrapper while retaining the original
# JSON-RPC implementation for all supported methods.
app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/mcp"
        and "POST" in getattr(route, "methods", set())
    )
]


@app.post("/mcp")
async def hardened_mcp_gateway(
    request: Request,
    authorization: str | None = Header(default=None),
    x_beeza_identity: str | None = Header(default=None, alias="X-Beeza-Identity"),
    db: Session = Depends(db_session),
):
    actor = phase11_app.require_external("protocol:use")(
        authorization=authorization,
        x_beeza_identity=x_beeza_identity,
    )
    try:
        payload = await request.json()
    except Exception:
        return await _original_mcp_gateway(request, actor, db)
    if isinstance(payload, dict) and payload.get("method") == "tools/call":
        params = payload.get("params") or {}
        if str(params.get("name") or "") == "beeza_get_task":
            arguments = params.get("arguments") or {}
            row = db.scalar(
                select(ProtocolTask).where(
                    ProtocolTask.task_id == str(arguments.get("task_id") or "")
                )
            )
            if row is not None and row.client_identity != actor and not has_permission(db, actor, "protocol:operate"):
                return phase11_app.mcp_result(
                    payload.get("id"),
                    {
                        "content": [{"type": "text", "text": "Protocol task not found"}],
                        "isError": True,
                    },
                )
    return await _original_mcp_gateway(request, actor, db)
