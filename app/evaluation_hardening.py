from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

import evaluation_service
import phase9_app
from collaboration_models import CollaborationTask
from collaboration_service import collaboration_event
from evaluation_models import EvaluationRun, EvidenceRecord, ReplayRun, policy_view
from main import Mission, RuntimeDispatch, SessionLocal, bounded_payload, utcnow


def clean_result(task: CollaborationTask) -> dict[str, Any]:
    result = evaluation_service.result_payload(task)
    result.pop("verification", None)
    return result


def stable_snapshot(
    task: CollaborationTask,
    dispatch: RuntimeDispatch | None,
) -> dict[str, Any]:
    return {
        "task": {
            "task_key": task.task_key,
            "mission_key": task.mission_key,
            "title": task.title,
            "objective": task.objective,
            "target_identity": task.target_identity,
            "target_runtime_key": task.target_runtime_key,
            "review_policy": task.review_policy,
            "priority": task.priority,
            "expected_outputs": task.expected_outputs,
            "acceptance_criteria": task.acceptance_criteria,
            "result": clean_result(task),
        },
        "dispatch": {
            "dispatch_key": dispatch.dispatch_key,
            "runtime_key": dispatch.runtime_key,
            "remote_id": dispatch.remote_id,
            "status": dispatch.status,
            "output": bounded_payload(dispatch.output or {}, max_chars=12000),
            "error": dispatch.error,
        } if dispatch else None,
    }


def evaluation_proxy(task: CollaborationTask) -> SimpleNamespace:
    return SimpleNamespace(
        title=task.title,
        objective=task.objective,
        acceptance_criteria=list(task.acceptance_criteria or []),
        priority=task.priority,
        status=task.status,
        review_policy=task.review_policy,
        result=clean_result(task),
    )


def dispatch_for_task(db: Session, task: CollaborationTask) -> RuntimeDispatch | None:
    if not task.dispatch_key:
        return None
    return db.scalar(
        select(RuntimeDispatch).where(
            RuntimeDispatch.dispatch_key == task.dispatch_key
        )
    )


def stable_result_hash(db: Session, task: CollaborationTask) -> str:
    return evaluation_service.canonical_hash(
        stable_snapshot(task, dispatch_for_task(db, task))
    )


def stable_evaluate_task(
    db: Session,
    task: CollaborationTask,
    *,
    evaluator_identity: str = "service:evaluator",
    force: bool = False,
    note: str | None = None,
) -> EvaluationRun:
    policy = evaluation_service.active_policy(db)
    dispatch = dispatch_for_task(db, task)
    snapshot = stable_snapshot(task, dispatch)
    result_hash = evaluation_service.canonical_hash(snapshot)
    existing = db.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.task_key == task.task_key,
            EvaluationRun.result_hash == result_hash,
            EvaluationRun.policy_key == policy.policy_key,
        )
        .order_by(EvaluationRun.created_at.desc())
    )
    if existing is not None and not force:
        return existing

    proxy = evaluation_proxy(task)
    evidence = evaluation_service.evidence_items(proxy, dispatch)
    components, findings = evaluation_service.evaluate_components(
        proxy, dispatch, policy, evidence
    )
    weights = evaluation_service.normalized_weights(policy)
    score = round(
        sum(components.get(key, 0.0) * weight for key, weight in weights.items()),
        4,
    )
    hard_failure = any(item.get("severity") == "ERROR" for item in findings)
    if score >= policy.pass_score and not hard_failure:
        status = "PASS"
    elif score >= policy.warn_score and not any(
        item.get("code") in {"MISSING_PROVENANCE", "STATUS_RESULT_CONFLICT"}
        for item in findings
    ):
        status = "WARN"
    else:
        status = "FAIL"
    recommendation = evaluation_service.recommendation_for(status, task)
    now = utcnow()
    evaluation = EvaluationRun(
        evaluation_key=f"EVAL-{uuid4().hex[:14].upper()}",
        mission_key=task.mission_key,
        task_key=task.task_key,
        policy_key=policy.policy_key,
        evaluator_identity=evaluator_identity,
        status=status,
        score=score,
        recommendation=recommendation,
        result_hash=result_hash,
        source_status=task.status,
        source_dispatch_key=task.dispatch_key,
        components=components,
        findings=bounded_payload([
            *findings,
            *([{"severity": "INFO", "code": "EVALUATOR_NOTE", "message": note}] if note else []),
        ], max_chars=12000),
        evidence_count=len([item for item in evidence if item.get("supporting")]),
        snapshot=bounded_payload(snapshot, max_chars=20000),
        created_at=now,
    )
    db.add(evaluation)
    db.flush()
    for item in evidence:
        db.add(
            EvidenceRecord(
                evidence_key=f"EVID-{uuid4().hex[:14].upper()}",
                evaluation_key=evaluation.evaluation_key,
                mission_key=task.mission_key,
                task_key=task.task_key,
                evidence_type=item["type"],
                title=item["title"],
                locator=item["locator"],
                content_hash=item["content_hash"],
                strength=item["strength"],
                metadata_json=bounded_payload(item["metadata"], max_chars=5000),
                created_at=now,
            )
        )

    result = evaluation_service.result_payload(task)
    result["verification"] = {
        "evaluation_key": evaluation.evaluation_key,
        "status": status,
        "score": score,
        "recommendation": recommendation,
        "evidence_count": evaluation.evidence_count,
        "evaluated_at": now.isoformat(),
        "result_hash": result_hash,
    }
    task.result = bounded_payload(result, max_chars=12000)
    task.updated_at = now
    if status == "FAIL" and policy.reopen_failed_auto_tasks and task.status == "COMPLETED":
        task.status = "REVIEW"
        task.next_follow_up_at = None
        mission = db.scalar(
            select(Mission).where(Mission.mission_key == task.mission_key)
        )
        if mission:
            mission.status = "WAITING_APPROVAL"
            mission.waiting_for = f"Verification failed for {task.task_key}"

    # Forced re-checks of the same immutable result remain auditable but do not
    # repeatedly move the agent reliability score.
    if existing is None:
        evaluation_service.update_agent_quality(
            db, task, score, status, evaluation.evaluation_key
        )
    collaboration_event(
        db,
        task,
        f"EVALUATION_{status}",
        evaluator_identity,
        f"{task.task_key} evaluated {status} at {score:.1%}; {recommendation}.",
        {
            "evaluation_key": evaluation.evaluation_key,
            "result_hash": result_hash,
            "score": score,
            "components": components,
            "recommendation": recommendation,
            "findings": evaluation.findings,
            "forced": force,
        },
        "ERROR" if status == "FAIL" else "WARNING" if status == "WARN" else "INFO",
    )
    return evaluation


_original_create_replay = evaluation_service.create_replay
_original_update_replay_state = evaluation_service.update_replay_state


def hardened_create_replay(
    db: Session,
    source: CollaborationTask,
    **kwargs: Any,
):
    replay = _original_create_replay(db, source, **kwargs)
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == replay.replay_task_key
        )
    )
    if task is None:
        return replay
    preferred_runtime = kwargs.get("preferred_runtime_key")
    target_identity = kwargs.get("target_identity")
    mode = str(kwargs.get("mode") or "REROUTE").upper()
    context = dict(task.context or {})
    if mode != "SAME":
        routing = dict(context.get("routing") or {})
        if preferred_runtime:
            context["preferred_runtime_key"] = preferred_runtime
            routing["preferred_runtime_key"] = preferred_runtime
            context["excluded_runtimes"] = [
                item for item in context.get("excluded_runtimes") or []
                if str(item).casefold() != str(preferred_runtime).casefold()
            ]
        if target_identity:
            target_key = str(target_identity).removeprefix("agent:").casefold()
            context["excluded_agents"] = [
                item for item in context.get("excluded_agents") or []
                if str(item).removeprefix("agent:").casefold() != target_key
            ]
        context["routing"] = routing
        task.context = bounded_payload(context)
    return replay


def complete_replay_state(db: Session, replay: ReplayRun) -> bool:
    before = (
        replay.status,
        json.dumps(replay.comparison or {}, sort_keys=True, default=str),
    )
    _original_update_replay_state(db, replay)
    source_eval = evaluation_service.latest_evaluation(db, replay.source_task_key)
    replay_eval = evaluation_service.latest_evaluation(db, replay.replay_task_key)
    if replay_eval is not None:
        source_score = source_eval.score if source_eval else None
        replay.comparison = {
            "source_evaluation_key": source_eval.evaluation_key if source_eval else None,
            "replay_evaluation_key": replay_eval.evaluation_key,
            "source_status": source_eval.status if source_eval else None,
            "replay_status": replay_eval.status,
            "source_score": source_score,
            "replay_score": replay_eval.score,
            "score_delta": round(replay_eval.score - source_score, 4)
            if source_score is not None else None,
            "improved": replay_eval.score > source_score
            if source_score is not None else None,
            "source_components": source_eval.components if source_eval else {},
            "replay_components": replay_eval.components,
        }
        replay.updated_at = utcnow()
    after = (
        replay.status,
        json.dumps(replay.comparison or {}, sort_keys=True, default=str),
    )
    return before != after


def fair_evaluation_tick() -> dict[str, int]:
    evaluated = passed = warned = failed = replay_updates = 0
    with SessionLocal() as db:
        policy = evaluation_service.seed_evaluation_policy(db)
        scan_limit = max(1000, evaluation_service.EVALUATOR_BATCH * 20)
        tasks = list(
            db.scalars(
                select(CollaborationTask)
                .where(
                    CollaborationTask.status.in_(
                        evaluation_service.EVALUATABLE_STATUSES
                    )
                )
                .order_by(CollaborationTask.updated_at.asc())
                .limit(scan_limit)
            ).all()
        )
        for task in tasks:
            result_hash = stable_result_hash(db, task)
            existing = db.scalar(
                select(EvaluationRun.id).where(
                    EvaluationRun.task_key == task.task_key,
                    EvaluationRun.result_hash == result_hash,
                    EvaluationRun.policy_key == policy.policy_key,
                ).limit(1)
            )
            if existing is not None:
                continue
            row = stable_evaluate_task(db, task)
            evaluated += 1
            passed += row.status == "PASS"
            warned += row.status == "WARN"
            failed += row.status == "FAIL"
            if evaluated >= evaluation_service.EVALUATOR_BATCH:
                break

        replays = list(
            db.scalars(
                select(ReplayRun)
                .order_by(ReplayRun.updated_at.asc())
                .limit(scan_limit)
            ).all()
        )
        for replay in replays:
            needs_update = (
                replay.status not in evaluation_service.REPLAY_TERMINAL_STATUSES
                or not replay.comparison
            )
            if needs_update:
                replay_updates += complete_replay_state(db, replay)
        db.commit()
    return {
        "evaluated": evaluated,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "replay_updates": replay_updates,
    }


def latest_evaluation_stats(db: Session) -> dict[str, Any]:
    policy = evaluation_service.active_policy(db)
    rows = list(
        db.scalars(
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc())
            .limit(10000)
        ).all()
    )
    latest_by_task: dict[str, EvaluationRun] = {}
    for row in rows:
        latest_by_task.setdefault(row.task_key, row)
    evaluations = list(latest_by_task.values())
    replays = list(
        db.scalars(
            select(ReplayRun)
            .order_by(ReplayRun.created_at.desc())
            .limit(10000)
        ).all()
    )
    counts = Counter(row.status for row in evaluations)
    replay_counts = Counter(row.status for row in replays)
    return {
        "policy": policy_view(policy),
        "evaluations": dict(sorted(counts.items())),
        "replays": dict(sorted(replay_counts.items())),
        "total_evaluations": len(evaluations),
        "total_evaluation_runs": len(rows),
        "total_replays": len(replays),
        "average_score": round(
            sum(row.score for row in evaluations) / max(1, len(evaluations)), 4
        ),
        "pass_rate": round(
            counts.get("PASS", 0) / max(1, len(evaluations)), 4
        ),
        "open_human_review": db.query(CollaborationTask)
        .filter(CollaborationTask.status == "REVIEW")
        .count(),
    }


evaluation_service.evaluate_task = stable_evaluate_task
phase9_app.evaluate_task = stable_evaluate_task
evaluation_service.create_replay = hardened_create_replay
phase9_app.create_replay = hardened_create_replay
evaluation_service.update_replay_state = complete_replay_state
phase9_app.update_replay_state = complete_replay_state
evaluation_service.evaluation_tick = fair_evaluation_tick
phase9_app.evaluation_tick = fair_evaluation_tick
evaluation_service.evaluation_stats = latest_evaluation_stats
phase9_app.evaluation_stats = latest_evaluation_stats
