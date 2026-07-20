from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask, TERMINAL_TASK_STATUSES, task_view
from collaboration_service import collaboration_event, create_message
from evaluation_models import (
    EvaluationPolicy,
    EvaluationRun,
    EvidenceRecord,
    ReplayRun,
    evaluation_view,
    evidence_view,
    policy_view,
    replay_view,
)
from main import (
    Mission,
    MissionEvent,
    RuntimeDispatch,
    SessionLocal,
    bounded_payload,
    redis_client,
    utcnow,
)
from registry_models import RegisteredAgent

EVALUATOR_ENABLED = os.getenv("BEEZA_EVALUATOR_ENABLED", "true").lower() not in {
    "0", "false", "no", "off",
}
EVALUATOR_INTERVAL = max(3.0, float(os.getenv("BEEZA_EVALUATOR_INTERVAL_SECONDS", "10")))
EVALUATOR_BATCH = max(1, min(500, int(os.getenv("BEEZA_EVALUATOR_BATCH_SIZE", "100"))))
EVALUATABLE_STATUSES = {"COMPLETED", "REVIEW", "FAILED", "BLOCKED"}
REPLAY_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

DEFAULT_WEIGHTS = {
    "completeness": 0.20,
    "acceptance": 0.20,
    "evidence": 0.20,
    "provenance": 0.15,
    "consistency": 0.10,
    "reproducibility": 0.10,
    "risk_disclosure": 0.05,
}


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalized_weights(policy: EvaluationPolicy) -> dict[str, float]:
    weights = {**DEFAULT_WEIGHTS, **(policy.weights or {})}
    positive = {key: max(0.0, float(value)) for key, value in weights.items()}
    total = sum(positive.values()) or 1.0
    return {key: value / total for key, value in positive.items()}


def seed_evaluation_policy(db: Session) -> EvaluationPolicy:
    row = db.scalar(
        select(EvaluationPolicy).where(
            EvaluationPolicy.policy_key == "policy:evidence-baseline"
        )
    )
    if row is not None:
        return row
    now = utcnow()
    row = EvaluationPolicy(
        policy_key="policy:evidence-baseline",
        name="Evidence and Acceptance Baseline",
        enabled=True,
        weights=DEFAULT_WEIGHTS,
        pass_score=0.78,
        warn_score=0.55,
        minimum_evidence=2,
        require_provenance=True,
        require_acceptance_coverage=True,
        reopen_failed_auto_tasks=True,
        settings={
            "acceptance_token_threshold": 0.55,
            "summary_minimum_chars": 40,
            "reliability_blend": 0.08,
            "candidate_evidence_keys": [
                "evidence", "sources", "references", "artifacts", "commands", "checks",
            ],
        },
        created_by="system:phase9",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def active_policy(db: Session) -> EvaluationPolicy:
    row = db.scalar(
        select(EvaluationPolicy)
        .where(EvaluationPolicy.enabled.is_(True))
        .order_by(EvaluationPolicy.id)
    )
    return row or seed_evaluation_policy(db)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def result_payload(task: CollaborationTask) -> dict[str, Any]:
    return dict(task.result or {}) if isinstance(task.result, dict) else {"value": task.result}


def result_text(task: CollaborationTask, dispatch: RuntimeDispatch | None) -> str:
    result = result_payload(task)
    pieces = [
        task.title,
        task.objective,
        text_value(result),
        text_value((dispatch.output or {}) if dispatch else {}),
    ]
    return "\n".join(piece for piece in pieces if piece).casefold()


def keyword_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\-]{3,}", value.casefold(), flags=re.UNICODE)
        if token not in {
            "the", "and", "for", "with", "from", "that", "this", "into", "must",
            "should", "result", "output", "task", "work", "provide", "return",
        }
    }


def criterion_covered(criterion: str, text: str, threshold: float) -> bool:
    phrase = " ".join(str(criterion).casefold().split())
    normalized_text = " ".join(text.split())
    if phrase and phrase in normalized_text:
        return True
    required = keyword_tokens(criterion)
    if not required:
        return False
    available = keyword_tokens(text)
    return len(required & available) / len(required) >= threshold


def evidence_type_for(key: str) -> str:
    mapping = {
        "sources": "SOURCE",
        "references": "REFERENCE",
        "artifacts": "ARTIFACT",
        "commands": "COMMAND",
        "checks": "CHECK",
        "evidence": "EVIDENCE",
    }
    return mapping.get(key, "EVIDENCE")


def evidence_items(task: CollaborationTask, dispatch: RuntimeDispatch | None) -> list[dict[str, Any]]:
    result = result_payload(task)
    items: list[dict[str, Any]] = []
    for key in ["evidence", "sources", "references", "artifacts", "commands", "checks"]:
        value = result.get(key)
        if value in (None, "", [], {}):
            continue
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            if isinstance(item, dict):
                title = str(
                    item.get("title")
                    or item.get("name")
                    or item.get("summary")
                    or item.get("type")
                    or f"{key.title()} {index + 1}"
                )
                locator = str(
                    item.get("url")
                    or item.get("path")
                    or item.get("locator")
                    or item.get("command")
                    or ""
                )
                metadata = bounded_payload(item, max_chars=5000)
            else:
                title = str(item)[:240]
                locator = str(item)[:1000] if key in {"sources", "references", "artifacts"} else ""
                metadata = {"value": str(item)[:4000]}
            content = {"key": key, "title": title, "locator": locator, "metadata": metadata}
            items.append({
                "type": evidence_type_for(key),
                "title": title[:240],
                "locator": locator[:1000],
                "content_hash": canonical_hash(content),
                "strength": 0.85 if key in {"sources", "checks", "artifacts"} else 0.70,
                "metadata": metadata,
                "supporting": True,
            })

    summary = str(result.get("summary") or result.get("output") or "").strip()
    if summary:
        items.append({
            "type": "CLAIM",
            "title": "Agent completion claim",
            "locator": "",
            "content_hash": canonical_hash(summary),
            "strength": 0.35,
            "metadata": {"preview": summary[:4000]},
            "supporting": False,
        })

    if dispatch is not None:
        provenance = {
            "dispatch_key": dispatch.dispatch_key,
            "runtime_key": dispatch.runtime_key,
            "remote_id": dispatch.remote_id,
            "status": dispatch.status,
            "updated_at": dispatch.updated_at.isoformat(),
        }
        items.append({
            "type": "PROVENANCE",
            "title": f"Runtime execution · {dispatch.runtime_key}",
            "locator": dispatch.remote_id or dispatch.dispatch_key,
            "content_hash": canonical_hash(provenance),
            "strength": 0.90 if dispatch.remote_id else 0.70,
            "metadata": provenance,
            "supporting": True,
        })

    deduplicated: dict[str, dict[str, Any]] = {}
    for item in items:
        deduplicated[item["content_hash"]] = item
    return list(deduplicated.values())


def evaluate_components(
    task: CollaborationTask,
    dispatch: RuntimeDispatch | None,
    policy: EvaluationPolicy,
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    result = result_payload(task)
    text = result_text(task, dispatch)
    findings: list[dict[str, Any]] = []
    summary = str(result.get("summary") or result.get("output") or "").strip()
    minimum_chars = int((policy.settings or {}).get("summary_minimum_chars", 40))
    summary_score = min(1.0, len(summary) / max(1, minimum_chars))
    output_keys = len([key for key, value in result.items() if value not in (None, "", [], {})])
    completeness = min(1.0, summary_score * 0.70 + min(1.0, output_keys / 4) * 0.30)
    if completeness < 0.60:
        findings.append({
            "severity": "ERROR",
            "code": "INCOMPLETE_RESULT",
            "message": "The result does not contain a sufficiently complete summary or structured outputs.",
        })

    criteria = [str(item).strip() for item in task.acceptance_criteria or [] if str(item).strip()]
    threshold = float((policy.settings or {}).get("acceptance_token_threshold", 0.55))
    coverage = [criterion_covered(item, text, threshold) for item in criteria]
    acceptance = sum(coverage) / len(coverage) if coverage else 1.0
    uncovered = [criterion for criterion, covered in zip(criteria, coverage) if not covered]
    if uncovered and policy.require_acceptance_coverage:
        findings.append({
            "severity": "WARNING" if acceptance >= 0.50 else "ERROR",
            "code": "ACCEPTANCE_GAPS",
            "message": f"{len(uncovered)} acceptance criteria are not evidenced in the result.",
            "items": uncovered[:20],
        })

    supporting = [item for item in evidence if item.get("supporting")]
    evidence_score = min(1.0, len(supporting) / max(1, policy.minimum_evidence)) if policy.minimum_evidence else 1.0
    if len(supporting) < policy.minimum_evidence:
        findings.append({
            "severity": "WARNING" if supporting else "ERROR",
            "code": "EVIDENCE_SHORTFALL",
            "message": f"Found {len(supporting)} supporting evidence items; policy requires {policy.minimum_evidence}.",
        })

    provenance = 0.0
    if dispatch is not None:
        provenance = 0.70
        if dispatch.remote_id:
            provenance = 1.0
        elif dispatch.dispatch_key and dispatch.runtime_key:
            provenance = 0.85
    elif result.get("runtime") and result.get("dispatch_key"):
        provenance = 0.70
    if policy.require_provenance and provenance < 0.70:
        findings.append({
            "severity": "ERROR",
            "code": "MISSING_PROVENANCE",
            "message": "The result cannot be tied to a runtime dispatch or remote execution identifier.",
        })

    has_error = bool(result.get("error"))
    status_success = task.status in {"COMPLETED", "REVIEW"}
    consistency = 1.0
    if status_success and has_error:
        consistency = 0.15
        findings.append({
            "severity": "ERROR",
            "code": "STATUS_RESULT_CONFLICT",
            "message": "The task reports successful completion while its result contains an error.",
        })
    elif not status_success and not has_error:
        consistency = 0.55
    elif not status_success and has_error:
        consistency = 0.85

    reproducible_types = {"COMMAND", "CHECK", "ARTIFACT", "SOURCE", "REFERENCE"}
    reproducible_count = sum(item["type"] in reproducible_types for item in evidence)
    reproducibility = min(1.0, reproducible_count / 2)
    if reproducibility < 0.50:
        findings.append({
            "severity": "WARNING",
            "code": "LOW_REPRODUCIBILITY",
            "message": "The result lacks commands, checks, artifacts or source locators needed to reproduce verification.",
        })

    risk_terms = {
        "risk", "rollback", "blocker", "limitation", "uncertain", "warning",
        "ความเสี่ยง", "ย้อนกลับ", "ข้อจำกัด", "ไม่แน่ใจ",
    }
    risk_disclosure = 1.0 if any(term in text for term in risk_terms) else 0.40
    if task.priority in {"HIGH", "CRITICAL"} and risk_disclosure < 0.50:
        findings.append({
            "severity": "WARNING",
            "code": "RISK_NOT_DISCLOSED",
            "message": "A high-priority result should state risks, limitations or rollback considerations.",
        })

    components = {
        "completeness": round(completeness, 4),
        "acceptance": round(acceptance, 4),
        "evidence": round(evidence_score, 4),
        "provenance": round(provenance, 4),
        "consistency": round(consistency, 4),
        "reproducibility": round(reproducibility, 4),
        "risk_disclosure": round(risk_disclosure, 4),
    }
    return components, findings


def recommendation_for(status: str, task: CollaborationTask) -> str:
    if status == "PASS":
        return "HUMAN_ACCEPT" if task.review_policy == "HUMAN" else "AUTO_ACCEPT"
    if status == "WARN":
        return "HUMAN_REVIEW"
    if status == "FAIL":
        return "REVISE_OR_REPLAY"
    return "INVESTIGATE"


def update_agent_quality(
    db: Session,
    task: CollaborationTask,
    score: float,
    status: str,
    evaluation_key: str,
) -> None:
    identity_key = str(task.target_identity or "")
    agent = db.scalar(
        select(RegisteredAgent).where(
            RegisteredAgent.identity_key == identity_key
        )
    )
    if agent is None:
        return
    profile = dict(agent.profile or {})
    quality = dict(profile.get("evaluation_quality") or {})
    quality["total"] = int(quality.get("total") or 0) + 1
    quality[status.lower()] = int(quality.get(status.lower()) or 0) + 1
    quality["last_score"] = round(score, 4)
    quality["last_evaluation_key"] = evaluation_key
    profile["evaluation_quality"] = quality
    blend = min(0.25, max(0.01, float((active_policy(db).settings or {}).get("reliability_blend", 0.08))))
    agent.reliability_score = round(
        min(1.0, max(0.0, agent.reliability_score * (1.0 - blend) + score * blend)),
        4,
    )
    agent.profile = profile
    agent.updated_at = utcnow()


def evaluate_task(
    db: Session,
    task: CollaborationTask,
    *,
    evaluator_identity: str = "service:evaluator",
    force: bool = False,
    note: str | None = None,
) -> EvaluationRun:
    policy = active_policy(db)
    dispatch = None
    if task.dispatch_key:
        dispatch = db.scalar(
            select(RuntimeDispatch).where(
                RuntimeDispatch.dispatch_key == task.dispatch_key
            )
        )
    snapshot = {
        "task": task_view(task),
        "dispatch": {
            "dispatch_key": dispatch.dispatch_key,
            "runtime_key": dispatch.runtime_key,
            "remote_id": dispatch.remote_id,
            "status": dispatch.status,
            "output": bounded_payload(dispatch.output or {}, max_chars=12000),
            "error": dispatch.error,
        } if dispatch else None,
    }
    result_hash = canonical_hash(snapshot)
    if not force:
        existing = db.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.task_key == task.task_key,
                EvaluationRun.result_hash == result_hash,
                EvaluationRun.policy_key == policy.policy_key,
            )
            .order_by(EvaluationRun.created_at.desc())
        )
        if existing is not None:
            return existing

    evidence = evidence_items(task, dispatch)
    components, findings = evaluate_components(task, dispatch, policy, evidence)
    weights = normalized_weights(policy)
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
    recommendation = recommendation_for(status, task)
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

    result = result_payload(task)
    result["verification"] = {
        "evaluation_key": evaluation.evaluation_key,
        "status": status,
        "score": score,
        "recommendation": recommendation,
        "evidence_count": evaluation.evidence_count,
        "evaluated_at": now.isoformat(),
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
    update_agent_quality(db, task, score, status, evaluation.evaluation_key)
    collaboration_event(
        db,
        task,
        f"EVALUATION_{status}",
        evaluator_identity,
        f"{task.task_key} evaluated {status} at {score:.1%}; {recommendation}.",
        {
            "evaluation_key": evaluation.evaluation_key,
            "score": score,
            "components": components,
            "recommendation": recommendation,
            "findings": evaluation.findings,
        },
        "ERROR" if status == "FAIL" else "WARNING" if status == "WARN" else "INFO",
    )
    return evaluation


def evaluation_detail(db: Session, row: EvaluationRun) -> dict[str, Any]:
    evidence = list(
        db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.evaluation_key == row.evaluation_key)
            .order_by(EvidenceRecord.id)
        ).all()
    )
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == row.task_key
        )
    )
    return {
        **evaluation_view(row),
        "evidence": [evidence_view(item) for item in evidence],
        "task": task_view(task) if task else None,
    }


def latest_evaluation(db: Session, task_key: str) -> EvaluationRun | None:
    return db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.task_key == task_key)
        .order_by(EvaluationRun.created_at.desc())
    )


def create_replay(
    db: Session,
    source: CollaborationTask,
    *,
    mode: str,
    reason: str,
    requested_by: str,
    preferred_runtime_key: str | None = None,
    target_identity: str | None = None,
    auto_dispatch: bool = True,
) -> ReplayRun:
    if source.status not in TERMINAL_TASK_STATUSES | {"REVIEW", "BLOCKED"}:
        raise ValueError("Replay requires a completed, reviewed, blocked or failed source task")
    now = utcnow()
    mode = mode.upper()
    source_context = dict(source.context or {})
    source_routing = dict(source_context.get("routing") or {})
    selected_agent = source_routing.get("selected_agent_key")
    selected_runtime = source_routing.get("selected_runtime_key") or source.target_runtime_key
    replay_key = f"REPLAY-{uuid4().hex[:14].upper()}"
    replay_task_key = f"TASK-{uuid4().hex[:12].upper()}"
    context = {
        **source_context,
        "replay": {
            "replay_key": replay_key,
            "source_task_key": source.task_key,
            "mode": mode,
            "reason": reason,
            "requested_by": requested_by,
        },
    }
    context.pop("force_reroute", None)
    context.pop("routing", None)
    if mode == "SAME":
        replay_target = target_identity or source.target_identity
        replay_runtime = preferred_runtime_key or source.target_runtime_key
        context["routing_mode"] = "FIXED"
    else:
        replay_target = target_identity or "agent:auto"
        replay_runtime = preferred_runtime_key or "auto"
        context["routing_mode"] = "FAILOVER" if mode == "FAILOVER" else "AUTO"
        context["excluded_agents"] = list(dict.fromkeys([
            *(source_context.get("excluded_agents") or []),
            *([selected_agent] if selected_agent else []),
        ]))
        context["excluded_runtimes"] = list(dict.fromkeys([
            *(source_context.get("excluded_runtimes") or []),
            *([selected_runtime] if selected_runtime else []),
        ]))
        context["routing"] = {
            "mode": context["routing_mode"],
            "status": "QUEUED",
            "attempts": 0,
        }
    task = CollaborationTask(
        task_key=replay_task_key,
        mission_key=source.mission_key,
        parent_task_key=source.task_key,
        title=f"Replay · {source.title}"[:240],
        objective=source.objective,
        source_identity=requested_by,
        target_identity=replay_target,
        target_runtime_key=replay_runtime,
        status="QUEUED",
        priority=source.priority,
        review_policy="HUMAN",
        auto_dispatch=auto_dispatch,
        depends_on=[],
        inputs=bounded_payload(source.inputs or []),
        expected_outputs=list(source.expected_outputs or []),
        acceptance_criteria=list(source.acceptance_criteria or []),
        context=bounded_payload(context),
        result={},
        dispatch_key=None,
        attempts=0,
        follow_up_count=0,
        last_progress_at=now,
        next_follow_up_at=None,
        deadline_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    snapshot = {
        "task": task_view(source),
        "evaluation": evaluation_view(latest_evaluation(db, source.task_key))
        if latest_evaluation(db, source.task_key) else None,
    }
    replay = ReplayRun(
        replay_key=replay_key,
        mission_key=source.mission_key,
        source_task_key=source.task_key,
        replay_task_key=replay_task_key,
        status="QUEUED",
        mode=mode,
        requested_by=requested_by,
        reason=reason,
        source_snapshot=bounded_payload(snapshot, max_chars=20000),
        comparison={},
        created_at=now,
        updated_at=now,
    )
    db.add(replay)
    create_message(
        db,
        mission_key=source.mission_key,
        task_key=replay_task_key,
        message_type="HANDOFF",
        source_identity=requested_by,
        target_identity=replay_target,
        subject=f"Replay {source.task_key}",
        body=reason,
        payload={
            "replay_key": replay_key,
            "source_task_key": source.task_key,
            "mode": mode,
            "target_runtime_key": replay_runtime,
        },
        status="DELIVERED",
        reply_required=True,
    )
    collaboration_event(
        db,
        task,
        "REPLAY_CREATED",
        requested_by,
        f"Created {mode} replay {replay_key} from {source.task_key}.",
        {"replay_key": replay_key, "source_task_key": source.task_key, "mode": mode},
    )
    db.add(
        MissionEvent(
            mission_key=source.mission_key,
            actor=requested_by[:80],
            event_type="REPLAY_CREATED",
            message=f"{replay_key}: {source.task_key} → {replay_task_key} ({mode})."[:800],
            created_at=now,
        )
    )
    return replay


def update_replay_state(db: Session, replay: ReplayRun) -> bool:
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == replay.replay_task_key
        )
    )
    if task is None:
        replay.status = "FAILED"
        replay.comparison = {"error": "Replay task no longer exists"}
        replay.updated_at = utcnow()
        return True
    previous = replay.status
    if task.status in {"QUEUED", "WAITING_DEPENDENCY", "REVISION"}:
        replay.status = "QUEUED"
    elif task.status in {"DISPATCHING", "RUNNING", "WAITING_APPROVAL", "REVIEW"}:
        replay.status = "RUNNING"
    elif task.status == "COMPLETED":
        replay.status = "COMPLETED"
    elif task.status in {"FAILED", "BLOCKED"}:
        replay.status = "FAILED"
    elif task.status == "CANCELLED":
        replay.status = "CANCELLED"

    if replay.status in REPLAY_TERMINAL_STATUSES:
        source_eval = latest_evaluation(db, replay.source_task_key)
        replay_eval = latest_evaluation(db, replay.replay_task_key)
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
                "improved": replay_eval.score > source_score if source_score is not None else None,
                "source_components": source_eval.components if source_eval else {},
                "replay_components": replay_eval.components,
            }
    replay.updated_at = utcnow()
    return replay.status != previous


def evaluation_tick() -> dict[str, int]:
    evaluated = passed = warned = failed = replay_updates = 0
    with SessionLocal() as db:
        seed_evaluation_policy(db)
        tasks = list(
            db.scalars(
                select(CollaborationTask)
                .where(CollaborationTask.status.in_(EVALUATABLE_STATUSES))
                .order_by(CollaborationTask.updated_at.desc())
                .limit(EVALUATOR_BATCH)
            ).all()
        )
        for task in tasks:
            before = latest_evaluation(db, task.task_key)
            row = evaluate_task(db, task)
            if before is None or before.evaluation_key != row.evaluation_key:
                evaluated += 1
                passed += row.status == "PASS"
                warned += row.status == "WARN"
                failed += row.status == "FAIL"
        replays = list(
            db.scalars(
                select(ReplayRun)
                .where(ReplayRun.status.not_in(REPLAY_TERMINAL_STATUSES))
                .order_by(ReplayRun.updated_at)
                .limit(EVALUATOR_BATCH)
            ).all()
        )
        for replay in replays:
            replay_updates += update_replay_state(db, replay)
        db.commit()
    return {
        "evaluated": evaluated,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "replay_updates": replay_updates,
    }


async def evaluator_worker() -> None:
    while True:
        try:
            result = evaluation_tick()
            redis_client.hset(
                "beezaoffice:evaluator-worker",
                mapping={
                    "status": "online",
                    "last_tick_at": utcnow().isoformat(),
                    "last_evaluated": str(result["evaluated"]),
                    "last_passed": str(result["passed"]),
                    "last_warned": str(result["warned"]),
                    "last_failed": str(result["failed"]),
                    "last_replay_updates": str(result["replay_updates"]),
                    "interval_seconds": str(EVALUATOR_INTERVAL),
                    "last_error": "",
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset(
                "beezaoffice:evaluator-worker",
                mapping={
                    "status": "degraded",
                    "last_tick_at": utcnow().isoformat(),
                    "last_error": str(exc)[:500],
                },
            )
        await asyncio.sleep(EVALUATOR_INTERVAL)


def evaluation_stats(db: Session) -> dict[str, Any]:
    policy = active_policy(db)
    evaluations = list(
        db.scalars(
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc())
            .limit(1000)
        ).all()
    )
    replays = list(
        db.scalars(
            select(ReplayRun)
            .order_by(ReplayRun.created_at.desc())
            .limit(1000)
        ).all()
    )
    counts = Counter(row.status for row in evaluations)
    replay_counts = Counter(row.status for row in replays)
    return {
        "policy": policy_view(policy),
        "evaluations": dict(sorted(counts.items())),
        "replays": dict(sorted(replay_counts.items())),
        "total_evaluations": len(evaluations),
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
