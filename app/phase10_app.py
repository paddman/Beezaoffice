from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import governance_service
import phase9_runtime  # noqa: F401 — install Phase 1–9 and hardened evaluation runtime
from collaboration_models import CollaborationTask, task_view
from evaluation_service import latest_evaluation
from governance_models import GovernanceIdentity, GovernanceRole, RoleBinding
from main import Mission, SessionLocal, app, db_session, redis_client, utcnow
from phase6_app import require_governance
from sop_models import (
    SOPNodeDecision,
    SOPNodeRun,
    SOPRun,
    SOPRunCreate,
    SOPTemplate,
    SOPTemplateCreate,
    SOPVersion,
    SOPVersionCreate,
    node_run_view,
    run_view,
    template_view,
    version_view,
)
from sop_service import (
    SOP_BATCH,
    SOP_ENABLED,
    SOP_INTERVAL,
    advance_run,
    cancel_run,
    canonical_checksum,
    decide_node,
    get_run,
    get_template,
    get_version,
    instantiate_run,
    published_version,
    run_node_rows,
    seed_sop_templates,
    sop_stats,
    sop_tick,
    sop_worker,
    validate_definition,
)

app.version = "0.11.0"
_sop_worker_task: asyncio.Task[None] | None = None

_PHASE10_ROUTE_RULES = [
    ("POST", re.compile(r"^/api/sop/tick$"), "sop:run"),
    ("POST", re.compile(r"^/api/sop/templates$"), "sop:write"),
    ("POST", re.compile(r"^/api/sop/templates/[^/]+/versions$"), "sop:write"),
    ("POST", re.compile(r"^/api/sop/versions/[^/]+/publish$"), "sop:publish"),
    ("POST", re.compile(r"^/api/sop/templates/[^/]+/runs$"), "sop:run"),
    ("POST", re.compile(r"^/api/sop/runs/[^/]+/tick$"), "sop:run"),
    ("POST", re.compile(r"^/api/sop/runs/[^/]+/cancel$"), "sop:run"),
    ("POST", re.compile(r"^/api/sop/runs/[^/]+/nodes/[^/]+/decision$"), "sop:approve"),
    ("POST", re.compile(r"^/api/sop/derive/[^/]+$"), "sop:write"),
]
for rule in reversed(_PHASE10_ROUTE_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)

# Starting or approving a workflow can release consequential work.
governance_service.EXECUTION_ACTIONS.update({"sop:run", "sop:approve"})


class SOPDeriveRequest(BaseModel):
    template_key: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9._-]*$")
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=3000)
    category: str = Field(default="Derived", min_length=2, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)


def ensure_sop_permissions(db: Session) -> None:
    additions = {
        "role:executive": {"sop:read", "sop:write", "sop:publish", "sop:run", "sop:approve"},
        "role:manager": {"sop:read", "sop:write", "sop:run", "sop:approve"},
        "role:operator": {"sop:read", "sop:run", "sop:approve"},
        "role:auditor": {"sop:read"},
        "role:agent": {"sop:read"},
        "role:service": {"sop:read", "sop:run"},
        "role:runtime": {"sop:read"},
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


def seed_sop_identity(db: Session) -> None:
    now = utcnow()
    identity_key = "service:sop"
    identity = db.scalar(
        select(GovernanceIdentity).where(GovernanceIdentity.identity_key == identity_key)
    )
    if identity is None:
        db.add(
            GovernanceIdentity(
                identity_key=identity_key,
                tenant_key="tenant:beeza",
                identity_type="SERVICE",
                display_name="Beeza SOP Orchestrator",
                department_key="dept:operations",
                status="ACTIVE",
                clearance="RESTRICTED",
                daily_budget_usd=2000.0,
                monthly_budget_usd=50000.0,
                attributes={
                    "seeded": True,
                    "purpose": "versioned SOP execution, approvals and rollback orchestration",
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
                created_by="system:phase10",
                created_at=now,
            )
        )
    db.commit()


@app.on_event("startup")
async def start_sop_runtime() -> None:
    global _sop_worker_task
    with SessionLocal() as db:
        ensure_sop_permissions(db)
        seed_sop_identity(db)
        seed_sop_templates(db)
    if not SOP_ENABLED:
        redis_client.hset("beezaoffice:sop-worker", mapping={"status": "disabled"})
        return
    if _sop_worker_task is None or _sop_worker_task.done():
        _sop_worker_task = asyncio.create_task(sop_worker(), name="beeza-sop-worker")


@app.on_event("shutdown")
async def stop_sop_runtime() -> None:
    global _sop_worker_task
    if _sop_worker_task is None:
        return
    _sop_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _sop_worker_task
    _sop_worker_task = None


def run_detail(db: Session, run: SOPRun) -> dict[str, Any]:
    template = get_template(db, run.template_key)
    version = get_version(db, run.version_key)
    nodes = run_node_rows(db, run.run_key)
    task_keys = [row.task_key for row in nodes if row.task_key]
    tasks = {
        task.task_key: task_view(task)
        for task in db.scalars(
            select(CollaborationTask).where(CollaborationTask.task_key.in_(task_keys))
        ).all()
    } if task_keys else {}
    return {
        **run_view(run),
        "template": template_view(template) if template else None,
        "version": version_view(version) if version else None,
        "nodes": [
            {**node_run_view(row), "task": tasks.get(row.task_key) if row.task_key else None}
            for row in nodes
        ],
        "stats": {
            "nodes": len([row for row in nodes if row.node_type != "ROLLBACK"]),
            "completed": sum(row.status == "COMPLETED" for row in nodes),
            "waiting_approval": sum(row.status == "WAITING_APPROVAL" for row in nodes),
            "failed": sum(row.status == "FAILED" for row in nodes),
            "rollback_nodes": sum(row.node_type == "ROLLBACK" for row in nodes),
        },
    }


@app.get("/api/sop/status")
def read_sop_status(
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    worker = redis_client.hgetall("beezaoffice:sop-worker")
    return {
        "enabled": SOP_ENABLED,
        "worker": {
            "status": worker.get("status", "starting"),
            "last_tick_at": worker.get("last_tick_at"),
            "last_processed": int(worker.get("last_processed", "0") or 0),
            "last_completed": int(worker.get("last_completed", "0") or 0),
            "last_failed": int(worker.get("last_failed", "0") or 0),
            "last_waiting": int(worker.get("last_waiting", "0") or 0),
            "interval_seconds": float(worker.get("interval_seconds", str(SOP_INTERVAL))),
            "last_error": worker.get("last_error"),
        },
        "batch_size": SOP_BATCH,
        "stats": sop_stats(db),
    }


@app.post("/api/sop/tick")
async def run_sop_tick(
    _: str = Depends(require_governance("sop:run")),
) -> dict[str, Any]:
    return {"ok": True, **(await asyncio.to_thread(sop_tick))}


@app.get("/api/sop/templates")
def list_sop_templates(
    status: str | None = Query(default=None, max_length=30),
    category: str | None = Query(default=None, max_length=100),
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(SOPTemplate)
    if status:
        statement = statement.where(SOPTemplate.status == status.upper())
    if category:
        statement = statement.where(SOPTemplate.category == category)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            SOPTemplate.name.ilike(pattern) | SOPTemplate.description.ilike(pattern)
        )
    rows = db.scalars(
        statement.order_by(SOPTemplate.category, SOPTemplate.name).limit(limit)
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        version = published_version(db, row)
        run_count = db.scalar(
            select(func.count(SOPRun.id)).where(SOPRun.template_key == row.template_key)
        ) or 0
        result.append({
            **template_view(row),
            "published_version": version_view(version) if version else None,
            "run_count": int(run_count),
        })
    return result


@app.post("/api/sop/templates", status_code=201)
def create_sop_template(
    payload: SOPTemplateCreate,
    actor: str = Depends(require_governance("sop:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if get_template(db, payload.template_key):
        raise HTTPException(status_code=409, detail="SOP template key already exists")
    try:
        definition = validate_definition(payload.definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = utcnow()
    template = SOPTemplate(
        template_key=payload.template_key,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        status="DRAFT",
        current_version=1,
        input_schema=payload.input_schema,
        tags=sorted(set(payload.tags)),
        owner_identity=actor,
        created_at=now,
        updated_at=now,
    )
    definition_json = definition.model_dump(mode="json")
    version = SOPVersion(
        version_key=f"{payload.template_key}:v1",
        template_key=payload.template_key,
        version_number=1,
        status="DRAFT",
        definition=definition_json,
        checksum=canonical_checksum(definition_json),
        changelog=payload.changelog,
        created_by=actor,
        created_at=now,
        published_at=None,
    )
    db.add(template)
    db.add(version)
    db.commit()
    db.refresh(template)
    return {**template_view(template), "versions": [version_view(version)]}


@app.get("/api/sop/templates/{template_key}")
def read_sop_template(
    template_key: str,
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    template = get_template(db, template_key)
    if template is None:
        raise HTTPException(status_code=404, detail="SOP template not found")
    versions = db.scalars(
        select(SOPVersion)
        .where(SOPVersion.template_key == template_key)
        .order_by(SOPVersion.version_number.desc())
    ).all()
    runs = db.scalars(
        select(SOPRun)
        .where(SOPRun.template_key == template_key)
        .order_by(SOPRun.created_at.desc())
        .limit(100)
    ).all()
    return {
        **template_view(template),
        "versions": [version_view(row) for row in versions],
        "runs": [run_view(row) for row in runs],
    }


@app.post("/api/sop/templates/{template_key}/versions", status_code=201)
def create_sop_version(
    template_key: str,
    payload: SOPVersionCreate,
    actor: str = Depends(require_governance("sop:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    template = get_template(db, template_key)
    if template is None:
        raise HTTPException(status_code=404, detail="SOP template not found")
    try:
        definition = validate_definition(payload.definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    next_number = int(
        db.scalar(
            select(func.max(SOPVersion.version_number)).where(
                SOPVersion.template_key == template_key
            )
        ) or 0
    ) + 1
    now = utcnow()
    definition_json = definition.model_dump(mode="json")
    version = SOPVersion(
        version_key=f"{template_key}:v{next_number}",
        template_key=template_key,
        version_number=next_number,
        status="DRAFT",
        definition=definition_json,
        checksum=canonical_checksum(definition_json),
        changelog=payload.changelog,
        created_by=actor,
        created_at=now,
        published_at=None,
    )
    template.current_version = next_number
    template.status = "DRAFT"
    template.updated_at = now
    db.add(version)
    db.commit()
    db.refresh(version)
    return version_view(version)


@app.post("/api/sop/versions/{version_key}/publish")
def publish_sop_version(
    version_key: str,
    actor: str = Depends(require_governance("sop:publish")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    version = get_version(db, version_key)
    if version is None:
        raise HTTPException(status_code=404, detail="SOP version not found")
    if version.status != "DRAFT":
        raise HTTPException(status_code=409, detail=f"Version cannot publish from {version.status}")
    try:
        definition = validate_definition(version.definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    checksum = canonical_checksum(definition.model_dump(mode="json"))
    if checksum != version.checksum:
        raise HTTPException(status_code=409, detail="Draft checksum does not match its definition")
    template = get_template(db, version.template_key)
    if template is None:
        raise HTTPException(status_code=409, detail="SOP template is missing")
    previous = db.scalars(
        select(SOPVersion).where(
            SOPVersion.template_key == version.template_key,
            SOPVersion.status == "PUBLISHED",
        )
    ).all()
    for row in previous:
        row.status = "DEPRECATED"
    now = utcnow()
    version.status = "PUBLISHED"
    version.published_at = now
    template.status = "PUBLISHED"
    template.current_version = version.version_number
    template.updated_at = now
    db.commit()
    db.refresh(version)
    return {**version_view(version), "published_by": actor}


@app.get("/api/sop/runs")
def list_sop_runs(
    template_key: str | None = Query(default=None, max_length=100),
    mission_key: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(SOPRun)
    if template_key:
        statement = statement.where(SOPRun.template_key == template_key)
    if mission_key:
        statement = statement.where(SOPRun.mission_key == mission_key)
    if status:
        statement = statement.where(SOPRun.status == status.upper())
    rows = db.scalars(
        statement.order_by(SOPRun.created_at.desc()).limit(limit)
    ).all()
    return [run_view(row) for row in rows]


@app.post("/api/sop/templates/{template_key}/runs", status_code=201)
def create_sop_run(
    template_key: str,
    payload: SOPRunCreate,
    version_key: str | None = Query(default=None, max_length=120),
    actor: str = Depends(require_governance("sop:run")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    template = get_template(db, template_key)
    if template is None:
        raise HTTPException(status_code=404, detail="SOP template not found")
    version = get_version(db, version_key) if version_key else published_version(db, template)
    if version is None or version.template_key != template_key:
        raise HTTPException(status_code=409, detail="Published SOP version not found")
    try:
        run = instantiate_run(
            db,
            template,
            version,
            inputs=payload.inputs,
            actor=actor,
            mission_title=payload.mission_title,
            mission_priority=payload.mission_priority,
            commander=payload.commander,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return run_detail(db, run)


@app.get("/api/sop/runs/{run_key}")
def read_sop_run(
    run_key: str,
    _: str = Depends(require_governance("sop:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    run = get_run(db, run_key)
    if run is None:
        raise HTTPException(status_code=404, detail="SOP run not found")
    return run_detail(db, run)


@app.post("/api/sop/runs/{run_key}/tick")
def tick_sop_run(
    run_key: str,
    _: str = Depends(require_governance("sop:run")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if get_run(db, run_key) is None:
        raise HTTPException(status_code=404, detail="SOP run not found")
    result = advance_run(db, run_key)
    run = get_run(db, run_key)
    return {"result": result, "run": run_detail(db, run)}


@app.post("/api/sop/runs/{run_key}/nodes/{node_key}/decision")
def decide_sop_node(
    run_key: str,
    node_key: str,
    payload: SOPNodeDecision,
    actor: str = Depends(require_governance("sop:approve")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    run = get_run(db, run_key)
    if run is None:
        raise HTTPException(status_code=404, detail="SOP run not found")
    try:
        decide_node(
            db,
            run,
            node_key,
            decision=payload.decision,
            actor=actor,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = advance_run(db, run_key)
    run = get_run(db, run_key)
    return {"result": result, "run": run_detail(db, run)}


@app.post("/api/sop/runs/{run_key}/cancel")
def cancel_sop_run(
    run_key: str,
    note: str = Query(default="Cancelled by operator", max_length=2000),
    actor: str = Depends(require_governance("sop:run")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    run = get_run(db, run_key)
    if run is None:
        raise HTTPException(status_code=404, detail="SOP run not found")
    try:
        cancel_run(db, run, actor=actor, note=note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_detail(db, run)


def derived_node_key(task: CollaborationTask, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-") or task.task_key.lower()
    base = base[:80]
    key = base
    counter = 2
    while key in used:
        key = f"{base[:75]}-{counter}"
        counter += 1
    used.add(key)
    return key


@app.post("/api/sop/derive/{mission_key}", status_code=201)
def derive_sop_from_mission(
    mission_key: str,
    payload: SOPDeriveRequest,
    actor: str = Depends(require_governance("sop:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if get_template(db, payload.template_key):
        raise HTTPException(status_code=409, detail="SOP template key already exists")
    mission = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    tasks = list(
        db.scalars(
            select(CollaborationTask)
            .where(
                CollaborationTask.mission_key == mission_key,
                CollaborationTask.status.in_(["COMPLETED", "REVIEW"]),
            )
            .order_by(CollaborationTask.created_at)
        ).all()
    )
    verified: list[CollaborationTask] = []
    for task in tasks:
        evaluation = latest_evaluation(db, task.task_key)
        if evaluation is not None and evaluation.status == "PASS":
            verified.append(task)
    if not verified:
        raise HTTPException(
            status_code=409,
            detail="Mission has no PASS-verified collaboration tasks to derive",
        )
    used: set[str] = set()
    key_by_task = {task.task_key: derived_node_key(task, used) for task in verified}
    nodes: list[dict[str, Any]] = []
    for task in verified:
        context = task.context or {}
        dependencies = [key_by_task[key] for key in task.depends_on or [] if key in key_by_task]
        routing_mode = str(context.get("routing_mode") or "FIXED").upper()
        if task.target_identity == "agent:auto" or task.target_runtime_key == "auto":
            routing_mode = "AUTO"
        nodes.append({
            "key": key_by_task[task.task_key],
            "title": task.title,
            "node_type": "TASK",
            "depends_on": dependencies,
            "objective": task.objective,
            "source_identity": "service:sop",
            "target_identity": None if routing_mode != "FIXED" else task.target_identity,
            "target_runtime_key": None if routing_mode != "FIXED" else task.target_runtime_key,
            "routing_mode": routing_mode if routing_mode in {"AUTO", "BEST", "FAILOVER", "FIXED"} else "AUTO",
            "priority": task.priority,
            "review_policy": task.review_policy,
            "auto_dispatch": True,
            "required_skills": context.get("required_skills") or [],
            "required_capabilities": context.get("required_capabilities") or [],
            "required_tools": context.get("required_tools") or [],
            "required_clearance": context.get("required_clearance") or "INTERNAL",
            "preferred_department": context.get("preferred_department"),
            "maximum_cost_usd": context.get("maximum_cost_usd"),
            "estimated_tokens": context.get("estimated_tokens"),
            "expected_outputs": task.expected_outputs or [],
            "acceptance_criteria": task.acceptance_criteria or [],
            "inputs": task.inputs or [],
            "verification_required": True,
        })
    try:
        definition = validate_definition({
            "nodes": nodes,
            "rollback_on_failure": False,
            "stop_on_failure": True,
            "settings": {
                "derived_from_mission": mission_key,
                "verified_task_keys": [task.task_key for task in verified],
            },
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = utcnow()
    template = SOPTemplate(
        template_key=payload.template_key,
        name=payload.name,
        description=payload.description or f"Derived from verified mission {mission_key}: {mission.title}",
        category=payload.category,
        status="DRAFT",
        current_version=1,
        input_schema={"type": "object", "properties": {}},
        tags=sorted(set([*payload.tags, "derived", "verified"])),
        owner_identity=actor,
        created_at=now,
        updated_at=now,
    )
    definition_json = definition.model_dump(mode="json")
    version = SOPVersion(
        version_key=f"{payload.template_key}:v1",
        template_key=payload.template_key,
        version_number=1,
        status="DRAFT",
        definition=definition_json,
        checksum=canonical_checksum(definition_json),
        changelog=f"Derived from {len(verified)} PASS-verified tasks in mission {mission_key}",
        created_by=actor,
        created_at=now,
        published_at=None,
    )
    db.add(template)
    db.add(version)
    db.commit()
    db.refresh(template)
    return {
        **template_view(template),
        "version": version_view(version),
        "derived_from": mission_key,
        "verified_tasks": [task.task_key for task in verified],
    }
