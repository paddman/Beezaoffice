from __future__ import annotations

import asyncio
import contextlib
import os
import re
from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import governance_service
import phase8_runtime  # noqa: F401 — install Phase 1–8 and hardened scheduler runtime
from collaboration_models import CollaborationTask, task_view
from evaluation_models import (
    EvaluationPolicy,
    EvaluationPolicyUpdate,
    EvaluationRequest,
    EvaluationRun,
    EvidenceRecord,
    ReplayCreate,
    ReplayRun,
    evaluation_view,
    evidence_view,
    policy_view,
    replay_view,
)
from evaluation_service import (
    EVALUATOR_BATCH,
    EVALUATOR_ENABLED,
    EVALUATOR_INTERVAL,
    active_policy,
    create_replay,
    evaluate_task,
    evaluation_detail,
    evaluation_stats,
    evaluation_tick,
    evaluator_worker,
    latest_evaluation,
    seed_evaluation_policy,
    update_replay_state,
)
from governance_models import GovernanceRole
from main import SessionLocal, app, db_session, redis_client, utcnow
from phase6_app import require_governance

app.version = "0.10.0"
_evaluator_worker_task: asyncio.Task[None] | None = None

_PHASE9_ROUTE_RULES = [
    ("POST", re.compile(r"^/api/evaluation/tick$"), "evaluation:run"),
    ("POST", re.compile(r"^/api/evaluation/tasks/[^/]+$"), "evaluation:run"),
    ("PATCH", re.compile(r"^/api/evaluation/policies/[^/]+$"), "evaluation:policy:write"),
    ("POST", re.compile(r"^/api/evaluation/replays$"), "replay:create"),
]
for rule in reversed(_PHASE9_ROUTE_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)


def ensure_evaluation_permissions(db: Session) -> None:
    additions = {
        "role:executive": {
            "evaluation:read", "evaluation:run", "evaluation:policy:write", "replay:create",
        },
        "role:manager": {"evaluation:read", "evaluation:run", "replay:create"},
        "role:operator": {"evaluation:read", "evaluation:run", "replay:create"},
        "role:auditor": {"evaluation:read"},
        "role:agent": {"evaluation:read"},
        "role:service": {"evaluation:read", "evaluation:run", "replay:create"},
        "role:runtime": {"evaluation:read"},
    }
    changed = False
    for role_key, permissions in additions.items():
        role = db.scalar(
            select(GovernanceRole).where(GovernanceRole.role_key == role_key)
        )
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
async def start_evaluator() -> None:
    global _evaluator_worker_task
    with SessionLocal() as db:
        ensure_evaluation_permissions(db)
        seed_evaluation_policy(db)
    if not EVALUATOR_ENABLED:
        redis_client.hset("beezaoffice:evaluator-worker", mapping={"status": "disabled"})
        return
    if _evaluator_worker_task is None or _evaluator_worker_task.done():
        _evaluator_worker_task = asyncio.create_task(
            evaluator_worker(), name="beeza-evaluator-worker"
        )


@app.on_event("shutdown")
async def stop_evaluator() -> None:
    global _evaluator_worker_task
    if _evaluator_worker_task is None:
        return
    _evaluator_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _evaluator_worker_task
    _evaluator_worker_task = None


@app.get("/api/evaluation/status")
def read_evaluation_status(
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    worker = redis_client.hgetall("beezaoffice:evaluator-worker")
    return {
        "enabled": EVALUATOR_ENABLED,
        "worker": {
            "status": worker.get("status", "starting"),
            "last_tick_at": worker.get("last_tick_at"),
            "last_evaluated": int(worker.get("last_evaluated", "0") or 0),
            "last_passed": int(worker.get("last_passed", "0") or 0),
            "last_warned": int(worker.get("last_warned", "0") or 0),
            "last_failed": int(worker.get("last_failed", "0") or 0),
            "last_replay_updates": int(worker.get("last_replay_updates", "0") or 0),
            "interval_seconds": float(
                worker.get("interval_seconds", str(EVALUATOR_INTERVAL))
            ),
            "last_error": worker.get("last_error"),
        },
        "batch_size": EVALUATOR_BATCH,
        "stats": evaluation_stats(db),
    }


@app.post("/api/evaluation/tick")
async def run_evaluation_tick(
    _: str = Depends(require_governance("evaluation:run")),
) -> dict[str, Any]:
    result = await asyncio.to_thread(evaluation_tick)
    return {"ok": True, **result}


@app.get("/api/evaluation/policies")
def list_evaluation_policies(
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(EvaluationPolicy).order_by(EvaluationPolicy.name)
    ).all()
    return [policy_view(row) for row in rows]


@app.patch("/api/evaluation/policies/{policy_key}")
def update_evaluation_policy(
    policy_key: str,
    payload: EvaluationPolicyUpdate,
    actor: str = Depends(require_governance("evaluation:policy:write")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(EvaluationPolicy).where(
            EvaluationPolicy.policy_key == policy_key
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evaluation policy not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("pass_score") is not None and changes.get("warn_score") is not None:
        if changes["warn_score"] > changes["pass_score"]:
            raise HTTPException(
                status_code=422,
                detail="warn_score cannot exceed pass_score",
            )
    for field, value in changes.items():
        if field in {"weights", "settings"} and value is not None:
            value = {**(getattr(row, field) or {}), **value}
        setattr(row, field, value)
    if row.warn_score > row.pass_score:
        raise HTTPException(status_code=422, detail="warn_score cannot exceed pass_score")
    row.settings = {**(row.settings or {}), "updated_by": actor}
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return policy_view(row)


@app.get("/api/evaluation/runs")
def list_evaluation_runs(
    mission_key: str | None = Query(default=None, max_length=80),
    task_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    recommendation: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(EvaluationRun)
    if mission_key:
        statement = statement.where(EvaluationRun.mission_key == mission_key)
    if task_key:
        statement = statement.where(EvaluationRun.task_key == task_key)
    if status:
        statement = statement.where(EvaluationRun.status == status.upper())
    if recommendation:
        statement = statement.where(
            EvaluationRun.recommendation == recommendation.upper()
        )
    rows = db.scalars(
        statement.order_by(EvaluationRun.created_at.desc()).limit(limit)
    ).all()
    return [evaluation_view(row) for row in rows]


@app.get("/api/evaluation/runs/{evaluation_key}")
def read_evaluation_run(
    evaluation_key: str,
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.evaluation_key == evaluation_key
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return evaluation_detail(db, row)


@app.get("/api/evaluation/tasks/{task_key}")
def read_task_evaluation(
    task_key: str,
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == task_key
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    row = latest_evaluation(db, task_key)
    return {
        "task": task_view(task),
        "evaluation": evaluation_detail(db, row) if row else None,
    }


@app.post("/api/evaluation/tasks/{task_key}")
def evaluate_collaboration_task(
    task_key: str,
    payload: EvaluationRequest,
    actor: str = Depends(require_governance("evaluation:run")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == task_key
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Collaboration task not found")
    if task.status not in {"COMPLETED", "REVIEW", "FAILED", "BLOCKED"}:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot be evaluated while status is {task.status}",
        )
    row = evaluate_task(
        db,
        task,
        evaluator_identity=actor,
        force=payload.force,
        note=payload.note,
    )
    db.commit()
    db.refresh(row)
    return evaluation_detail(db, row)


@app.get("/api/evaluation/evidence")
def list_evidence(
    evaluation_key: str | None = Query(default=None, max_length=100),
    mission_key: str | None = Query(default=None, max_length=80),
    task_key: str | None = Query(default=None, max_length=100),
    evidence_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=500, ge=1, le=2000),
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(EvidenceRecord)
    if evaluation_key:
        statement = statement.where(EvidenceRecord.evaluation_key == evaluation_key)
    if mission_key:
        statement = statement.where(EvidenceRecord.mission_key == mission_key)
    if task_key:
        statement = statement.where(EvidenceRecord.task_key == task_key)
    if evidence_type:
        statement = statement.where(
            EvidenceRecord.evidence_type == evidence_type.upper()
        )
    rows = db.scalars(
        statement.order_by(EvidenceRecord.created_at.desc()).limit(limit)
    ).all()
    return [evidence_view(row) for row in rows]


@app.get("/api/evaluation/replays")
def list_replays(
    mission_key: str | None = Query(default=None, max_length=80),
    task_key: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(ReplayRun)
    if mission_key:
        statement = statement.where(ReplayRun.mission_key == mission_key)
    if task_key:
        statement = statement.where(
            or_(
                ReplayRun.source_task_key == task_key,
                ReplayRun.replay_task_key == task_key,
            )
        )
    if status:
        statement = statement.where(ReplayRun.status == status.upper())
    rows = db.scalars(
        statement.order_by(ReplayRun.created_at.desc()).limit(limit)
    ).all()
    return [replay_view(row) for row in rows]


@app.get("/api/evaluation/replays/{replay_key}")
def read_replay(
    replay_key: str,
    _: str = Depends(require_governance("evaluation:read")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    replay = db.scalar(
        select(ReplayRun).where(ReplayRun.replay_key == replay_key)
    )
    if replay is None:
        raise HTTPException(status_code=404, detail="Replay not found")
    update_replay_state(db, replay)
    source = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == replay.source_task_key
        )
    )
    replay_task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == replay.replay_task_key
        )
    )
    db.commit()
    return {
        **replay_view(replay),
        "source_task": task_view(source) if source else None,
        "replay_task": task_view(replay_task) if replay_task else None,
        "source_evaluation": evaluation_view(latest_evaluation(db, replay.source_task_key))
        if latest_evaluation(db, replay.source_task_key) else None,
        "replay_evaluation": evaluation_view(latest_evaluation(db, replay.replay_task_key))
        if latest_evaluation(db, replay.replay_task_key) else None,
    }


@app.post("/api/evaluation/replays", status_code=201)
def create_evaluation_replay(
    payload: ReplayCreate,
    actor: str = Depends(require_governance("replay:create")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    source = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == payload.source_task_key
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source task not found")
    try:
        replay = create_replay(
            db,
            source,
            mode=payload.mode,
            reason=payload.reason,
            requested_by=actor,
            preferred_runtime_key=payload.preferred_runtime_key,
            target_identity=payload.target_identity,
            auto_dispatch=payload.auto_dispatch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(replay)
    return replay_view(replay)
