from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import phase10_app
import sop_service
from collaboration_models import CollaborationTask
from main import SessionLocal, bounded_payload, redis_client, utcnow
from sop_models import SOPNodeDefinition, SOPNodeRun, SOPRun


def hardened_sync_task_node(
    db: Session,
    run: SOPRun,
    node: SOPNodeDefinition | None,
    node_run: SOPNodeRun,
) -> None:
    if not node_run.task_key:
        return
    task = db.scalar(
        select(CollaborationTask).where(
            CollaborationTask.task_key == node_run.task_key
        )
    )
    if task is None:
        node_run.status = "FAILED"
        node_run.error = "Collaboration task is missing"
        node_run.completed_at = utcnow()
        node_run.updated_at = utcnow()
        return

    node_run.output_payload = bounded_payload(task.result or {}, max_chars=12000)
    required = bool(node.verification_required) if node else False
    verification = sop_service.verification_state(task)

    # Verification is authoritative even when Phase 9 has reopened the task to REVIEW.
    if required and verification == "FAIL":
        node_run.status = "FAILED"
        node_run.error = "Evidence evaluation failed"
        node_run.completed_at = utcnow()
    elif required and verification == "WARN":
        node_run.status = "WAITING_APPROVAL"
        node_run.error = "Evidence evaluation warned; human decision required"
    elif task.status == "COMPLETED":
        if required and verification is None:
            node_run.status = "RUNNING"
            node_run.output_payload = {
                **(node_run.output_payload or {}),
                "sop_waiting_for": "evaluation",
            }
        else:
            node_run.status = (
                "ROLLED_BACK"
                if node_run.node_type == "ROLLBACK"
                else "COMPLETED"
            )
            node_run.error = None
            node_run.completed_at = utcnow()
    elif task.status in {"REVIEW", "WAITING_APPROVAL"}:
        node_run.status = "WAITING_APPROVAL"
        node_run.error = "Task requires human approval"
    elif task.status in sop_service.TASK_TERMINAL_FAILURE:
        node_run.status = "FAILED"
        node_run.error = str(
            (task.result or {}).get("error") or f"Task ended as {task.status}"
        )[:2000]
        node_run.completed_at = utcnow()
    else:
        node_run.status = "RUNNING"
    node_run.updated_at = utcnow()


def rotating_run_keys(db: Session, scan_limit: int) -> list[str]:
    cursor = int(redis_client.get("beezaoffice:sop-run-cursor") or 0)
    rows = list(
        db.scalars(
            select(SOPRun)
            .where(
                SOPRun.status.in_(sop_service.ACTIVE_RUN_STATUSES),
                SOPRun.id > cursor,
            )
            .order_by(SOPRun.id.asc())
            .limit(scan_limit)
        ).all()
    )
    if not rows and cursor:
        rows = list(
            db.scalars(
                select(SOPRun)
                .where(SOPRun.status.in_(sop_service.ACTIVE_RUN_STATUSES))
                .order_by(SOPRun.id.asc())
                .limit(scan_limit)
            ).all()
        )
    redis_client.set(
        "beezaoffice:sop-run-cursor",
        str(rows[-1].id if rows else 0),
    )
    return [row.run_key for row in rows]


def fair_sop_tick() -> dict[str, int]:
    processed = completed = failed = waiting = 0
    with SessionLocal() as db:
        scan_limit = max(200, sop_service.SOP_BATCH * 10)
        keys = rotating_run_keys(db, scan_limit)
        for key in keys[: sop_service.SOP_BATCH]:
            result = sop_service.advance_run(db, key)
            processed += 1
            completed += result.get("status") == "COMPLETED"
            failed += result.get("status") == "FAILED"
            waiting += result.get("status") == "WAITING_APPROVAL"
    return {
        "processed": processed,
        "completed": completed,
        "failed": failed,
        "waiting": waiting,
    }


sop_service.sync_task_node = hardened_sync_task_node
sop_service.sop_tick = fair_sop_tick
phase10_app.sop_tick = fair_sop_tick
