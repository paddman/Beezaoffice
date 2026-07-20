from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

import evaluation_service
import phase9_app
from collaboration_models import CollaborationTask
from collaboration_service import collaboration_event
from evaluation_models import EvaluationRun, EvidenceRecord
from main import Mission, RuntimeDispatch, bounded_payload, utcnow


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


def stable_evaluate_task(
    db: Session,
    task: CollaborationTask,
    *,
    evaluator_identity: str = "service:evaluator",
    force: bool = False,
    note: str | None = None,
) -> EvaluationRun:
    policy = evaluation_service.active_policy(db)
    dispatch = None
    if task.dispatch_key:
        dispatch = db.scalar(
            select(RuntimeDispatch).where(
                RuntimeDispatch.dispatch_key == task.dispatch_key
            )
        )
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


evaluation_service.evaluate_task = stable_evaluate_task
phase9_app.evaluate_task = stable_evaluate_task
evaluation_service.create_replay = hardened_create_replay
phase9_app.create_replay = hardened_create_replay
