from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase10_runtime  # noqa: F401 — install Phase 1–10 and hardened SOP runtime
from collaboration_models import CollaborationTask
from governance_models import GovernanceIdentity, GovernanceRole, RoleBinding
from governance_service import execution_enabled, has_permission
from main import AUTH_TOKEN, SessionLocal, app, db_session, redis_client, utcnow
from phase6_app import require_governance
from protocol_models import (
    A2ASendRequest,
    OpenAIChatRequest,
    ProtocolEvent,
    ProtocolTask,
    TERMINAL_PROTOCOL_STATES,
    WebhookIngress,
    WebhookReceipt,
    protocol_task_view,
    webhook_receipt_view,
)
from protocol_service import (
    PROTOCOL_BATCH,
    PROTOCOL_ENABLED,
    PROTOCOL_INTERVAL,
    PROTOCOL_PUBLIC_URL,
    PROTOCOL_SYNC_TIMEOUT,
    a2a_task_view,
    add_protocol_event,
    create_protocol_task,
    get_protocol_task,
    message_text,
    openai_messages_text,
    protocol_stats,
    protocol_tick,
    protocol_worker,
    sync_protocol_task,
    wait_for_protocol_task,
    webhook_digest,
)
from registry_models import RegisteredAgent, agent_view
from sop_models import SOPRun
from sop_service import get_template, instantiate_run, published_version

app.version = "0.12.0"
_PROTOCOL_WORKER_TASK: asyncio.Task[None] | None = None
WEBHOOK_SECRET = os.getenv("BEEZA_WEBHOOK_SECRET", "").encode()
A2A_VERSION = "1.0"
MCP_PROTOCOL_VERSION = "2025-06-18"

_PHASE11_ROUTE_RULES = [
    ("POST", re.compile(r"^/api/protocol/tick$"), "protocol:operate"),
]
for rule in reversed(_PHASE11_ROUTE_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

governance_service.EXECUTION_ACTIONS.add("protocol:use")


def ensure_protocol_permissions(db: Session) -> None:
    additions = {
        "role:executive": {"protocol:read", "protocol:use", "protocol:operate"},
        "role:manager": {"protocol:read", "protocol:use", "protocol:operate"},
        "role:operator": {"protocol:read", "protocol:use", "protocol:operate"},
        "role:auditor": {"protocol:read"},
        "role:agent": {"protocol:read", "protocol:use"},
        "role:service": {"protocol:read", "protocol:use", "protocol:operate"},
        "role:runtime": {"protocol:read", "protocol:use"},
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


def seed_protocol_identity(db: Session) -> None:
    now = utcnow()
    identity_key = "service:protocol"
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == identity_key)
    )
    if identity is None:
        db.add(
            GovernanceIdentity(
                identity_key=identity_key,
                tenant_key="tenant:beeza",
                identity_type="SERVICE",
                display_name="Beeza Protocol Gateway",
                department_key="dept:platform",
                status="ACTIVE",
                clearance="RESTRICTED",
                daily_budget_usd=2500.0,
                monthly_budget_usd=75000.0,
                attributes={
                    "seeded": True,
                    "purpose": "A2A, MCP, OpenAI-compatible and webhook protocol ingress",
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
                created_by="system:phase11",
                created_at=now,
            )
        )
    db.commit()


@app.on_event("startup")
async def start_protocol_gateway() -> None:
    global _PROTOCOL_WORKER_TASK
    with SessionLocal() as db:
        ensure_protocol_permissions(db)
        seed_protocol_identity(db)
    if not PROTOCOL_ENABLED:
        redis_client.hset("beezaoffice:protocol-worker", mapping={"status": "disabled"})
        return
    if _PROTOCOL_WORKER_TASK is None or _PROTOCOL_WORKER_TASK.done():
        _PROTOCOL_WORKER_TASK = asyncio.create_task(
            protocol_worker(), name="beeza-protocol-worker"
        )


@app.on_event("shutdown")
async def stop_protocol_gateway() -> None:
    global _PROTOCOL_WORKER_TASK
    if _PROTOCOL_WORKER_TASK is None:
        return
    _PROTOCOL_WORKER_TASK.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _PROTOCOL_WORKER_TASK
    _PROTOCOL_WORKER_TASK = None


def require_external(permission: str) -> Callable[..., str]:
    def dependency(
        authorization: str | None = Header(default=None),
        x_beeza_identity: str | None = Header(default=None, alias="X-Beeza-Identity"),
    ) -> str:
        if AUTH_TOKEN and authorization != f"Bearer {AUTH_TOKEN}":
            raise HTTPException(status_code=401, detail="Invalid BeezaOffice token")
        actor = (x_beeza_identity or "service:protocol").strip() or "service:protocol"
        with SessionLocal() as db:
            identity = db.scalar(
                select(GovernanceIdentity).where(
                    GovernanceIdentity.identity_key == actor
                )
            )
            if identity is None or identity.status != "ACTIVE":
                raise HTTPException(status_code=403, detail="Protocol identity is not active")
            if not has_permission(db, actor, permission):
                raise HTTPException(status_code=403, detail=f"Missing permission {permission}")
        return actor

    return dependency


def ensure_execution(db: Session) -> None:
    if not execution_enabled(db):
        raise HTTPException(status_code=423, detail="Runtime execution is disabled by the emergency kill switch")


def ensure_permission(db: Session, actor: str, permission: str) -> None:
    if not has_permission(db, actor, permission):
        raise HTTPException(status_code=403, detail=f"Missing permission {permission}")


def validate_a2a_version(value: str | None) -> None:
    if value and not value.startswith("1.0"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported A2A-Version {value}; BeezaOffice supports {A2A_VERSION}",
        )


def agent_card(extended: bool = False) -> dict[str, Any]:
    card: dict[str, Any] = {
        "name": "BeezaOffice AI Workforce",
        "description": "Governed AI workforce gateway with intelligent routing, evidence verification, SOP execution and human approval.",
        "version": app.version,
        "protocolVersion": A2A_VERSION,
        "supportedInterfaces": [
            {
                "url": f"{PROTOCOL_PUBLIC_URL}/message:send",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": A2A_VERSION,
            }
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": True,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer"}
        },
        "security": [{"bearerAuth": []}],
        "skills": [
            {
                "id": "governed-task-execution",
                "name": "Governed task execution",
                "description": "Route work to OpenClaw, CherryAgent, Hermes or thClaws using skills, clearance, capacity, reliability and cost.",
                "tags": ["routing", "governance", "multi-agent"],
                "examples": ["Investigate this incident and return verified evidence"],
            },
            {
                "id": "verified-sop-run",
                "name": "Verified SOP execution",
                "description": "Execute versioned operating procedures with approval and rollback gates.",
                "tags": ["sop", "approval", "rollback", "evidence"],
                "examples": ["Run the verified incident-response procedure"],
            },
        ],
    }
    if extended:
        card["metadata"] = {
            "mcpEndpoint": f"{PROTOCOL_PUBLIC_URL}/mcp",
            "openAICompatibleEndpoint": f"{PROTOCOL_PUBLIC_URL}/v1/chat/completions",
            "webhookEndpointPattern": f"{PROTOCOL_PUBLIC_URL}/hooks/{{channel}}",
            "taskListEndpoint": f"{PROTOCOL_PUBLIC_URL}/tasks",
            "registeredRuntimes": ["openclaw", "cherryagent", "hermes", "thclaws"],
            "governance": ["RBAC", "clearance", "budget", "approval", "kill-switch", "audit"],
        }
    return card


@app.get("/.well-known/agent-card.json")
def read_public_agent_card() -> dict[str, Any]:
    return agent_card(False)


@app.get("/extendedAgentCard")
def read_extended_agent_card(
    _: str = Depends(require_external("protocol:read")),
) -> dict[str, Any]:
    return agent_card(True)


@app.get("/api/protocol/status")
def read_protocol_status(
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    worker = redis_client.hgetall("beezaoffice:protocol-worker")
    return {
        "enabled": PROTOCOL_ENABLED,
        "public_url": PROTOCOL_PUBLIC_URL,
        "a2a_version": A2A_VERSION,
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "sync_timeout_seconds": PROTOCOL_SYNC_TIMEOUT,
        "batch_size": PROTOCOL_BATCH,
        "worker": {
            "status": worker.get("status", "starting"),
            "last_tick_at": worker.get("last_tick_at"),
            "last_processed": int(worker.get("last_processed", "0") or 0),
            "last_changed": int(worker.get("last_changed", "0") or 0),
            "last_completed": int(worker.get("last_completed", "0") or 0),
            "last_failed": int(worker.get("last_failed", "0") or 0),
            "interval_seconds": float(worker.get("interval_seconds", str(PROTOCOL_INTERVAL))),
            "last_error": worker.get("last_error"),
        },
        "stats": protocol_stats(db),
        "interfaces": {
            "a2a": "/message:send",
            "mcp": "/mcp",
            "openai": "/v1/chat/completions",
            "webhook": "/hooks/{channel}",
            "events": "/api/protocol/events/stream",
        },
    }


@app.post("/api/protocol/tick")
async def run_protocol_tick(
    _: str = Depends(require_governance("protocol:operate")),
) -> dict[str, Any]:
    return {"ok": True, **(await asyncio.to_thread(protocol_tick))}


@app.get("/api/protocol/tasks")
def list_protocol_tasks(
    protocol: str | None = Query(default=None, max_length=40),
    state: str | None = Query(default=None, max_length=50),
    mission_key: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(ProtocolTask)
    if protocol:
        statement = statement.where(ProtocolTask.protocol == protocol.lower())
    if state:
        statement = statement.where(ProtocolTask.state == state.upper())
    if mission_key:
        statement = statement.where(ProtocolTask.mission_key == mission_key)
    rows = db.scalars(
        statement.order_by(ProtocolTask.created_at.desc()).limit(limit)
    ).all()
    return [protocol_task_view(row) for row in rows]


@app.get("/api/protocol/events")
def list_protocol_events(
    task_id: str | None = Query(default=None, max_length=120),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(ProtocolEvent).where(ProtocolEvent.sequence > after)
    if task_id:
        statement = statement.where(ProtocolEvent.task_id == task_id)
    rows = db.scalars(
        statement.order_by(ProtocolEvent.occurred_at.desc()).limit(limit)
    ).all()
    return [
        {
            "key": row.event_key,
            "task_id": row.task_id,
            "sequence": row.sequence,
            "type": row.event_type,
            "payload": row.payload,
            "occurred_at": row.occurred_at.isoformat(),
        }
        for row in rows
    ]


@app.get("/api/protocol/webhook-receipts")
def list_webhook_receipts(
    channel_key: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_governance("protocol:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(WebhookReceipt)
    if channel_key:
        statement = statement.where(WebhookReceipt.channel_key == channel_key)
    rows = db.scalars(
        statement.order_by(WebhookReceipt.received_at.desc()).limit(limit)
    ).all()
    return [webhook_receipt_view(row) for row in rows]


@app.post("/message:send")
async def a2a_send_message(
    payload: A2ASendRequest,
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
    actor: str = Depends(require_external("protocol:use")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    validate_a2a_version(a2a_version)
    ensure_execution(db)
    text = message_text(payload.message.parts)
    if not text:
        raise HTTPException(status_code=422, detail="A2A message contains no text or data")
    message_id = payload.message.messageId or f"msg-{uuid4()}"
    context_id = payload.message.contextId or f"ctx-{uuid4()}"
    metadata = {**payload.metadata, **payload.message.metadata}
    row = await create_protocol_task(
        db,
        protocol="a2a",
        client_identity=actor,
        message_id=message_id,
        context_id=context_id,
        text=text,
        title=str(metadata.get("title") or "A2A governed task"),
        priority=str(metadata.get("priority") or "NORMAL").upper(),
        required_skills=list(metadata.get("requiredSkills") or []),
        required_capabilities=list(metadata.get("requiredCapabilities") or []),
        required_tools=list(metadata.get("requiredTools") or []),
        required_clearance=str(metadata.get("requiredClearance") or "INTERNAL").upper(),
        preferred_runtime_key=metadata.get("preferredRuntimeKey"),
        fixed_runtime=bool(metadata.get("fixedRuntime")),
        metadata=metadata,
    )
    if not payload.configuration.returnImmediately:
        row = await wait_for_protocol_task(row.task_id) or row
    return {"task": a2a_task_view(row)}


@app.get("/tasks/{task_id}")
def a2a_get_task(
    task_id: str,
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
    _: str = Depends(require_external("protocol:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    validate_a2a_version(a2a_version)
    row = get_protocol_task(db, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="A2A task not found")
    sync_protocol_task(db, row)
    db.commit()
    return a2a_task_view(row)


@app.get("/tasks")
def a2a_list_tasks(
    context_id: str | None = Query(default=None, alias="contextId", max_length=180),
    state: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=100, ge=1, le=1000),
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
    actor: str = Depends(require_external("protocol:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    validate_a2a_version(a2a_version)
    statement = select(ProtocolTask).where(
        ProtocolTask.protocol == "a2a",
        ProtocolTask.client_identity == actor,
    )
    if context_id:
        statement = statement.where(ProtocolTask.context_id == context_id)
    if state:
        statement = statement.where(ProtocolTask.state == state.upper())
    rows = db.scalars(
        statement.order_by(ProtocolTask.created_at.desc()).limit(limit)
    ).all()
    return {"tasks": [a2a_task_view(row) for row in rows], "nextPageToken": None}


@app.post("/tasks/{task_id}:cancel")
def a2a_cancel_task(
    task_id: str,
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
    actor: str = Depends(require_external("protocol:use")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    validate_a2a_version(a2a_version)
    ensure_execution(db)
    row = get_protocol_task(db, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="A2A task not found")
    if row.client_identity != actor and not has_permission(db, actor, "protocol:operate"):
        raise HTTPException(status_code=403, detail="Task is not visible to this identity")
    if row.state in TERMINAL_PROTOCOL_STATES:
        return a2a_task_view(row)
    if row.collaboration_task_key:
        task = db.scalar(
            select(CollaborationTask).where(
                CollaborationTask.task_key == row.collaboration_task_key
            )
        )
        if task and task.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
            task.status = "CANCELLED"
            task.result = {
                **(task.result or {}),
                "protocol_cancellation": {
                    "actor": actor,
                    "at": utcnow().isoformat(),
                    "note": "Gateway cancellation stops new Beeza work; remote stop remains adapter-controlled.",
                },
            }
            task.updated_at = utcnow()
    row.state = "TASK_STATE_CANCELED"
    row.status_message = "Task canceled at the BeezaOffice gateway."
    row.completed_at = utcnow()
    row.updated_at = utcnow()
    add_protocol_event(db, row, "TASK_STATUS_UPDATE", {"state": row.state, "message": row.status_message})
    db.commit()
    return a2a_task_view(row)


@app.get("/tasks/{task_id}:subscribe")
async def a2a_subscribe_task(
    task_id: str,
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
    _: str = Depends(require_external("protocol:read")),
) -> StreamingResponse:
    validate_a2a_version(a2a_version)
    with SessionLocal() as db:
        if get_protocol_task(db, task_id) is None:
            raise HTTPException(status_code=404, detail="A2A task not found")

    async def stream():
        last_sequence = 0
        first = True
        while True:
            with SessionLocal() as db:
                row = get_protocol_task(db, task_id)
                if row is None:
                    return
                sync_protocol_task(db, row)
                db.commit()
                db.refresh(row)
                if first:
                    yield f"event: task\ndata: {json.dumps({'task': a2a_task_view(row)}, ensure_ascii=False, default=str)}\n\n"
                    first = False
                events = list(
                    db.scalars(
                        select(ProtocolEvent)
                        .where(
                            ProtocolEvent.task_id == task_id,
                            ProtocolEvent.sequence > last_sequence,
                        )
                        .order_by(ProtocolEvent.sequence.asc())
                    ).all()
                )
                for event in events:
                    last_sequence = max(last_sequence, event.sequence)
                    envelope_key = "artifactUpdate" if event.event_type == "TASK_ARTIFACT_UPDATE" else "statusUpdate"
                    envelope = {
                        envelope_key: {
                            "taskId": task_id,
                            "contextId": row.context_id,
                            "final": row.state in TERMINAL_PROTOCOL_STATES,
                            **(event.payload or {}),
                        }
                    }
                    yield f"event: {event.event_type}\ndata: {json.dumps(envelope, ensure_ascii=False, default=str)}\n\n"
                terminal = row.state in TERMINAL_PROTOCOL_STATES
            if terminal:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream")


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "beeza_list_agents",
            "description": "List governed BeezaOffice agents, skills, runtime preference and available capacity.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    "skill": {"type": "string"},
                },
            },
        },
        {
            "name": "beeza_create_task",
            "description": "Create a governed, intelligently routed BeezaOffice task and return its gateway task ID.",
            "inputSchema": {
                "type": "object",
                "required": ["objective"],
                "properties": {
                    "objective": {"type": "string"},
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["LOW", "NORMAL", "HIGH", "CRITICAL"]},
                    "required_skills": {"type": "array", "items": {"type": "string"}},
                    "preferred_runtime_key": {"type": "string"},
                },
            },
        },
        {
            "name": "beeza_get_task",
            "description": "Read a BeezaOffice protocol task and its evidence artifacts.",
            "inputSchema": {
                "type": "object",
                "required": ["task_id"],
                "properties": {"task_id": {"type": "string"}},
            },
        },
        {
            "name": "beeza_run_sop",
            "description": "Start a published BeezaOffice SOP as a governed mission.",
            "inputSchema": {
                "type": "object",
                "required": ["template_key"],
                "properties": {
                    "template_key": {"type": "string"},
                    "inputs": {"type": "object"},
                    "priority": {"type": "string", "enum": ["LOW", "NORMAL", "HIGH", "CRITICAL"]},
                },
            },
        },
    ]


def mcp_result(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def mcp_error(request_id: Any, code: int, message: str, data: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error})


@app.post("/mcp")
async def mcp_gateway(
    request: Request,
    actor: str = Depends(require_external("protocol:use")),
    db: Session = Depends(db_session),
) -> Response:
    try:
        payload = await request.json()
    except Exception:
        return mcp_error(None, -32700, "Parse error")
    request_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return mcp_error(request_id, -32600, "Invalid Request")
    method = str(payload.get("method") or "")
    params = payload.get("params") or {}

    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return mcp_result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "BeezaOffice", "version": app.version},
                "instructions": "Use Beeza tools through Governance. Credentials are never forwarded to downstream runtimes.",
            },
        )
    if method == "ping":
        return mcp_result(request_id, {})
    if method == "tools/list":
        return mcp_result(request_id, {"tools": mcp_tools()})
    if method != "tools/call":
        return mcp_error(request_id, -32601, "Method not found")

    tool_name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    try:
        if tool_name == "beeza_list_agents":
            ensure_permission(db, actor, "registry:read")
            limit = max(1, min(200, int(arguments.get("limit") or 50)))
            rows = list(
                db.scalars(
                    select(RegisteredAgent)
                    .where(RegisteredAgent.status == "ACTIVE")
                    .order_by(RegisteredAgent.display_name)
                    .limit(limit)
                ).all()
            )
            skill = str(arguments.get("skill") or "").casefold()
            if skill:
                rows = [row for row in rows if skill in {item.casefold() for item in row.skills or []}]
            content = [{"type": "text", "text": json.dumps([agent_view(row) for row in rows], ensure_ascii=False, default=str)}]
            return mcp_result(request_id, {"content": content, "isError": False})

        if tool_name == "beeza_get_task":
            ensure_permission(db, actor, "protocol:read")
            row = get_protocol_task(db, str(arguments.get("task_id") or ""))
            if row is None:
                raise ValueError("Protocol task not found")
            sync_protocol_task(db, row)
            db.commit()
            return mcp_result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(a2a_task_view(row), ensure_ascii=False, default=str)}], "isError": False},
            )

        if tool_name == "beeza_create_task":
            ensure_permission(db, actor, "scheduler:route")
            ensure_execution(db)
            objective = str(arguments.get("objective") or "").strip()
            if len(objective) < 10:
                raise ValueError("objective must contain at least 10 characters")
            row = await create_protocol_task(
                db,
                protocol="mcp",
                client_identity=actor,
                message_id=f"mcp-{request_id or uuid4()}",
                context_id=f"mcp-ctx-{uuid4()}",
                text=objective,
                title=str(arguments.get("title") or "MCP governed task"),
                priority=str(arguments.get("priority") or "NORMAL").upper(),
                required_skills=list(arguments.get("required_skills") or []),
                preferred_runtime_key=arguments.get("preferred_runtime_key"),
                metadata={"mcp_tool": tool_name},
            )
            return mcp_result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(a2a_task_view(row), ensure_ascii=False, default=str)}], "isError": False},
            )

        if tool_name == "beeza_run_sop":
            ensure_permission(db, actor, "sop:run")
            ensure_execution(db)
            template_key = str(arguments.get("template_key") or "")
            template = get_template(db, template_key)
            if template is None:
                raise ValueError("SOP template not found")
            version = published_version(db, template)
            if version is None:
                raise ValueError("SOP has no published version")
            run = instantiate_run(
                db,
                template,
                version,
                inputs=dict(arguments.get("inputs") or {}),
                actor=actor,
                mission_title=f"MCP SOP · {template.name}",
                mission_priority=str(arguments.get("priority") or "NORMAL").upper(),
                commander="Beeza Protocol Gateway",
            )
            return mcp_result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps({"run_key": run.run_key, "mission_key": run.mission_key, "status": run.status}, ensure_ascii=False)}], "isError": False},
            )

        return mcp_error(request_id, -32602, f"Unknown tool {tool_name}")
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return mcp_result(request_id, {"content": [{"type": "text", "text": str(message)}], "isError": True})


@app.post("/v1/chat/completions")
async def openai_chat_completion(
    payload: OpenAIChatRequest,
    actor: str = Depends(require_external("protocol:use")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if payload.stream:
        raise HTTPException(status_code=400, detail="Phase 11 OpenAI-compatible ingress supports stream=false; use A2A SSE for streaming")
    ensure_execution(db)
    text = openai_messages_text(payload.messages)
    runtime_key = None
    fixed_runtime = False
    if payload.model.startswith("beeza/"):
        candidate = payload.model.split("/", 1)[1]
        if candidate in {"openclaw", "cherryagent", "hermes", "thclaws"}:
            runtime_key = candidate
            fixed_runtime = True
    row = await create_protocol_task(
        db,
        protocol="openai",
        client_identity=actor,
        message_id=f"chatcmpl-request-{uuid4()}",
        context_id=payload.user or f"chat-{uuid4()}",
        text=text,
        title="OpenAI-compatible governed request",
        priority=str(payload.metadata.get("priority") or "NORMAL").upper(),
        required_skills=list(payload.metadata.get("required_skills") or []),
        required_capabilities=list(payload.metadata.get("required_capabilities") or []),
        required_tools=list(payload.metadata.get("required_tools") or []),
        required_clearance=str(payload.metadata.get("required_clearance") or "INTERNAL").upper(),
        preferred_runtime_key=runtime_key or payload.metadata.get("preferred_runtime_key"),
        fixed_runtime=fixed_runtime,
        metadata={"model": payload.model, **payload.metadata},
    )
    row = await wait_for_protocol_task(row.task_id) or row
    artifact_text = ""
    if row.artifacts:
        parts = row.artifacts[0].get("parts") or []
        artifact_text = next((str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("text")), "")
    content = artifact_text or json.dumps(
        {
            "status": row.state,
            "task_id": row.task_id,
            "mission_key": row.mission_key,
            "message": row.status_message,
            "poll": f"{PROTOCOL_PUBLIC_URL}/tasks/{row.task_id}",
        },
        ensure_ascii=False,
    )
    prompt_tokens = max(1, len(text) // 4)
    completion_tokens = max(1, len(content) // 4)
    return {
        "id": f"chatcmpl-{row.task_id.removeprefix('task-')}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop" if row.state == "TASK_STATE_COMPLETED" else "length",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "beeza": {
            "task_id": row.task_id,
            "mission_key": row.mission_key,
            "state": row.state,
            "collaboration_task_key": row.collaboration_task_key,
        },
    }


def webhook_authorized(request: Request, raw: bytes) -> bool:
    authorization = request.headers.get("Authorization")
    if AUTH_TOKEN and authorization == f"Bearer {AUTH_TOKEN}":
        return True
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Beeza-Signature", "")
        expected = "sha256=" + hmac.new(WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)
    return not AUTH_TOKEN


@app.post("/hooks/{channel_key}")
async def webhook_ingress(
    channel_key: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    raw = await request.body()
    if not webhook_authorized(request, raw):
        raise HTTPException(status_code=401, detail="Invalid webhook authentication")
    try:
        payload = WebhookIngress.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid webhook payload: {exc}") from exc
    actor = request.headers.get("X-Beeza-Identity", "service:protocol").strip() or "service:protocol"
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == actor)
    )
    if identity is None or identity.status != "ACTIVE" or not has_permission(db, actor, "protocol:use"):
        raise HTTPException(status_code=403, detail="Webhook identity cannot use the protocol gateway")
    ensure_execution(db)
    digest = webhook_digest(raw)
    idempotency_key = payload.idempotency_key or request.headers.get("Idempotency-Key") or digest
    existing = db.scalar(
        select(WebhookReceipt).where(
            WebhookReceipt.channel_key == channel_key,
            WebhookReceipt.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return webhook_receipt_view(existing)

    protocol_task_id = None
    sop_run_key = None
    response_payload: dict[str, Any]
    if payload.mode == "sop":
        ensure_permission(db, actor, "sop:run")
        if not payload.template_key:
            raise HTTPException(status_code=422, detail="template_key is required for SOP webhook mode")
        template = get_template(db, payload.template_key)
        if template is None:
            raise HTTPException(status_code=404, detail="SOP template not found")
        version = published_version(db, template)
        if version is None:
            raise HTTPException(status_code=409, detail="SOP has no published version")
        run = instantiate_run(
            db,
            template,
            version,
            inputs=payload.inputs,
            actor=actor,
            mission_title=payload.title or f"Webhook SOP · {template.name}",
            mission_priority=payload.priority,
            commander="Beeza Protocol Gateway",
        )
        sop_run_key = run.run_key
        response_payload = {"run_key": run.run_key, "mission_key": run.mission_key, "status": run.status}
    else:
        ensure_permission(db, actor, "scheduler:route")
        objective = (payload.objective or "").strip()
        if len(objective) < 10:
            raise HTTPException(status_code=422, detail="objective is required for task webhook mode")
        row = await create_protocol_task(
            db,
            protocol="webhook",
            client_identity=actor,
            message_id=f"webhook-{channel_key}-{idempotency_key}"[:180],
            context_id=f"webhook-{channel_key}",
            text=objective,
            title=payload.title or f"Webhook · {channel_key}",
            priority=payload.priority,
            required_skills=payload.required_skills,
            required_capabilities=payload.required_capabilities,
            required_tools=payload.required_tools,
            required_clearance=payload.required_clearance,
            preferred_runtime_key=payload.preferred_runtime_key,
            metadata={"channel_key": channel_key, **payload.metadata},
        )
        protocol_task_id = row.task_id
        response_payload = a2a_task_view(row)

    receipt = WebhookReceipt(
        receipt_key=f"HOOK-{uuid4().hex[:14].upper()}",
        channel_key=channel_key[:100],
        idempotency_key=idempotency_key[:180],
        client_identity=actor,
        mode=payload.mode,
        payload_hash=digest,
        protocol_task_id=protocol_task_id,
        sop_run_key=sop_run_key,
        status="ACCEPTED",
        response_payload=response_payload,
        received_at=utcnow(),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return webhook_receipt_view(receipt)


@app.get("/api/protocol/events/stream")
async def protocol_event_stream(
    after_id: int = Query(default=0, ge=0),
    _: str = Depends(require_governance("protocol:read")),
) -> StreamingResponse:
    async def stream():
        cursor = after_id
        while True:
            with SessionLocal() as db:
                rows = list(
                    db.scalars(
                        select(ProtocolEvent)
                        .where(ProtocolEvent.id > cursor)
                        .order_by(ProtocolEvent.id.asc())
                        .limit(200)
                    ).all()
                )
                for row in rows:
                    cursor = row.id
                    payload = {
                        "id": row.id,
                        "key": row.event_key,
                        "task_id": row.task_id,
                        "sequence": row.sequence,
                        "type": row.event_type,
                        "payload": row.payload,
                        "occurred_at": row.occurred_at.isoformat(),
                    }
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            if not rows:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream")
