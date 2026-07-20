from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from collaboration_models import CollaborationTask
from collaboration_service import collaboration_event, create_message
from main import Mission, MissionEvent, SessionLocal, bounded_payload, redis_client, utcnow
from phase3_app import RuntimeEvent
from sop_models import (
    SOPDefinition,
    SOPNodeDefinition,
    SOPNodeRun,
    SOPRun,
    SOPTemplate,
    SOPVersion,
)

SOP_ENABLED = os.getenv("BEEZA_SOP_ENABLED", "true").lower() not in {
    "0", "false", "no", "off",
}
SOP_INTERVAL = max(2.0, float(os.getenv("BEEZA_SOP_INTERVAL_SECONDS", "3")))
SOP_BATCH = max(1, min(500, int(os.getenv("BEEZA_SOP_BATCH_SIZE", "100"))))
ACTIVE_RUN_STATUSES = {"PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK"}
TASK_TERMINAL_FAILURE = {"FAILED", "BLOCKED", "CANCELLED", "ESCALATED"}
TOKEN_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def canonical_checksum(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_definition(definition: SOPDefinition | dict[str, Any]) -> SOPDefinition:
    model = definition if isinstance(definition, SOPDefinition) else SOPDefinition.model_validate(definition)
    keys = [node.key for node in model.nodes]
    if len(keys) != len(set(keys)):
        raise ValueError("SOP node keys must be unique")
    known = set(keys)
    for node in model.nodes:
        unknown = [item for item in node.depends_on if item not in known]
        if unknown:
            raise ValueError(f"Node {node.key} has unknown dependencies: {', '.join(unknown)}")
        if node.key in node.depends_on:
            raise ValueError(f"Node {node.key} cannot depend on itself")

    graph = {node.key: list(node.depends_on) for node in model.nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError(f"SOP definition contains a dependency cycle at {key}")
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in keys:
        visit(key)
    return model


def topological_order(definition: SOPDefinition) -> list[str]:
    remaining = {node.key: set(node.depends_on) for node in definition.nodes}
    ordered: list[str] = []
    while remaining:
        ready = sorted(key for key, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise ValueError("SOP definition contains a dependency cycle")
        ordered.extend(ready)
        for key in ready:
            remaining.pop(key)
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return ordered


def get_value(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def render_text(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        resolved = get_value(context, match.group(1))
        if resolved is None:
            return match.group(0)
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False, default=str)
        return str(resolved)

    return TOKEN_PATTERN.sub(replace, value)


def render_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render_text(value, context)
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, context) for key, item in value.items()}
    return value


def validate_inputs(template: SOPTemplate, inputs: dict[str, Any]) -> dict[str, Any]:
    schema = template.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = list(schema.get("required") or [])
    output = dict(inputs or {})
    for key, spec in properties.items():
        if key not in output and isinstance(spec, dict) and "default" in spec:
            output[key] = spec["default"]
    missing = [key for key in required if output.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing required SOP inputs: {', '.join(missing)}")
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key, spec in properties.items():
        if key not in output or not isinstance(spec, dict):
            continue
        expected = type_map.get(str(spec.get("type") or "").lower())
        if expected and not isinstance(output[key], expected):
            raise ValueError(f"SOP input {key} must be {spec.get('type')}")
    return bounded_payload(output, max_chars=20000)


def sop_event(
    db: Session,
    run: SOPRun,
    event_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any] | None = None,
    severity: str = "INFO",
) -> None:
    body = bounded_payload(payload or {}, max_chars=9000)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{run.run_key}|{event_type}|{run.status}|{message}|{encoded}".encode()
    ).hexdigest()[:40]
    key = f"sop:{run.run_key}:{event_type}:{digest}"[:180]
    if db.scalar(select(RuntimeEvent.id).where(RuntimeEvent.event_key == key)):
        return
    now = utcnow()
    db.add(
        RuntimeEvent(
            event_key=key,
            mission_key=run.mission_key,
            dispatch_key=run.run_key,
            runtime_key="beeza-sop",
            event_type=event_type,
            actor=actor[:120],
            message=message[:1000],
            severity=severity,
            payload=body if isinstance(body, dict) else {"value": body},
            occurred_at=now,
            created_at=now,
        )
    )


def seed_sop_templates(db: Session) -> None:
    if db.scalar(select(SOPTemplate.id).limit(1)) is not None:
        return
    now = utcnow()
    templates = [
        {
            "key": "incident-response",
            "name": "Verified Incident Response",
            "description": "Collect evidence, identify root cause, approve remediation, execute safely, verify recovery and publish the incident record.",
            "category": "Operations",
            "tags": ["incident", "operations", "verification", "rollback"],
            "input_schema": {
                "type": "object",
                "required": ["incident_summary", "affected_service"],
                "properties": {
                    "incident_summary": {"type": "string"},
                    "affected_service": {"type": "string"},
                    "change_window": {"type": "string", "default": "Emergency window"},
                },
            },
            "definition": {
                "rollback_on_failure": True,
                "stop_on_failure": True,
                "nodes": [
                    {
                        "key": "collect-evidence",
                        "title": "Collect verified evidence",
                        "objective": "Collect logs, metrics, recent changes and timestamps for {{input.affected_service}}. Incident: {{input.incident_summary}}",
                        "required_skills": ["metrics", "evidence"],
                        "required_tools": ["prometheus"],
                        "expected_outputs": ["timeline", "metric evidence", "change evidence"],
                        "acceptance_criteria": ["Evidence has timestamps", "Sources are identified"],
                        "verification_required": True,
                    },
                    {
                        "key": "analyze-root-cause",
                        "title": "Analyze root cause",
                        "depends_on": ["collect-evidence"],
                        "objective": "Analyze the evidence from SOP run {{run.key}} and identify the most likely root cause, competing hypotheses and confidence.",
                        "required_skills": ["triage", "linux"],
                        "expected_outputs": ["root-cause hypothesis", "risk analysis", "remediation options"],
                        "acceptance_criteria": ["Conclusion cites evidence", "Alternative hypotheses are addressed"],
                        "verification_required": True,
                    },
                    {
                        "key": "approve-remediation",
                        "title": "Approve remediation plan",
                        "node_type": "APPROVAL",
                        "depends_on": ["analyze-root-cause"],
                        "objective": "Human operator approves the selected remediation and rollback plan for {{input.affected_service}}.",
                        "verification_required": False,
                    },
                    {
                        "key": "execute-remediation",
                        "title": "Execute approved remediation",
                        "depends_on": ["approve-remediation"],
                        "objective": "Execute the approved remediation for {{input.affected_service}} during {{input.change_window}}. Preserve command output and rollback readiness.",
                        "priority": "CRITICAL",
                        "required_skills": ["linux", "proxmox"],
                        "required_tools": ["shell", "runbook"],
                        "expected_outputs": ["change record", "command evidence", "service state"],
                        "acceptance_criteria": ["Only approved change was applied", "Rollback remains available"],
                        "verification_required": True,
                        "rollback": {
                            "title": "Rollback incident remediation",
                            "objective": "Restore the previous known-good state for {{input.affected_service}}, preserve rollback evidence and report residual risk.",
                            "required_skills": ["linux"],
                            "required_tools": ["shell", "runbook"],
                            "acceptance_criteria": ["Previous state restored", "Service state verified"],
                        },
                    },
                    {
                        "key": "verify-recovery",
                        "title": "Verify service recovery",
                        "depends_on": ["execute-remediation"],
                        "objective": "Independently verify recovery of {{input.affected_service}} using metrics, health checks and user-impact indicators.",
                        "required_skills": ["verification", "evidence"],
                        "expected_outputs": ["verification checks", "before/after metrics", "remaining risks"],
                        "acceptance_criteria": ["Health checks pass", "Evidence demonstrates recovery"],
                        "verification_required": True,
                    },
                    {
                        "key": "publish-report",
                        "title": "Publish incident report",
                        "depends_on": ["verify-recovery"],
                        "objective": "Produce an executive incident report for {{input.affected_service}} containing timeline, root cause, remediation, evidence, business impact and prevention actions.",
                        "required_skills": ["reporting"],
                        "review_policy": "HUMAN",
                        "expected_outputs": ["executive summary", "technical timeline", "preventive actions"],
                        "acceptance_criteria": ["Report is evidence-backed", "Owners and follow-up actions are named"],
                        "verification_required": True,
                    },
                ],
            },
        },
        {
            "key": "daily-operations-brief",
            "name": "Daily Operations Brief",
            "description": "Gather operational health and risk in parallel, compose an executive brief and verify its supporting evidence.",
            "category": "Executive",
            "tags": ["daily", "brief", "operations"],
            "input_schema": {
                "type": "object",
                "required": ["report_date"],
                "properties": {
                    "report_date": {"type": "string"},
                    "audience": {"type": "string", "default": "Executive leadership"},
                },
            },
            "definition": {
                "rollback_on_failure": False,
                "stop_on_failure": True,
                "nodes": [
                    {
                        "key": "collect-health",
                        "title": "Collect service health",
                        "objective": "Collect verified infrastructure and service health for {{input.report_date}}.",
                        "required_skills": ["metrics"],
                        "expected_outputs": ["service health", "capacity status", "incident summary"],
                        "acceptance_criteria": ["Metrics have sources", "Critical services are covered"],
                    },
                    {
                        "key": "collect-risk",
                        "title": "Collect risk and approvals",
                        "objective": "Collect open risks, pending approvals, deadlines and budget exceptions for {{input.report_date}}.",
                        "required_skills": ["risk", "reporting"],
                        "expected_outputs": ["risk register", "approval queue", "deadline exceptions"],
                        "acceptance_criteria": ["Owners are identified", "Urgency is explicit"],
                    },
                    {
                        "key": "compose-brief",
                        "title": "Compose executive brief",
                        "depends_on": ["collect-health", "collect-risk"],
                        "objective": "Create a concise verified operations brief for {{input.audience}} using outputs from run {{run.key}}.",
                        "required_skills": ["briefing", "reporting"],
                        "review_policy": "HUMAN",
                        "expected_outputs": ["executive summary", "decisions required", "watch list"],
                        "acceptance_criteria": ["Claims cite evidence", "Required decisions are explicit"],
                    },
                ],
            },
        },
    ]
    for item in templates:
        definition = validate_definition(item["definition"])
        template = SOPTemplate(
            template_key=item["key"],
            name=item["name"],
            description=item["description"],
            category=item["category"],
            status="PUBLISHED",
            current_version=1,
            input_schema=item["input_schema"],
            tags=item["tags"],
            owner_identity="human:owner",
            created_at=now,
            updated_at=now,
        )
        db.add(template)
        db.add(
            SOPVersion(
                version_key=f"{item['key']}:v1",
                template_key=item["key"],
                version_number=1,
                status="PUBLISHED",
                definition=definition.model_dump(mode="json"),
                checksum=canonical_checksum(definition.model_dump(mode="json")),
                changelog="Seeded production baseline",
                created_by="system:phase10",
                created_at=now,
                published_at=now,
            )
        )
    db.commit()


def get_template(db: Session, template_key: str) -> SOPTemplate | None:
    return db.scalar(select(SOPTemplate).where(SOPTemplate.template_key == template_key))


def get_version(db: Session, version_key: str) -> SOPVersion | None:
    return db.scalar(select(SOPVersion).where(SOPVersion.version_key == version_key))


def get_run(db: Session, run_key: str) -> SOPRun | None:
    return db.scalar(select(SOPRun).where(SOPRun.run_key == run_key))


def published_version(db: Session, template: SOPTemplate) -> SOPVersion | None:
    return db.scalar(
        select(SOPVersion)
        .where(
            SOPVersion.template_key == template.template_key,
            SOPVersion.status == "PUBLISHED",
        )
        .order_by(SOPVersion.version_number.desc())
    )


def run_node_rows(db: Session, run_key: str) -> list[SOPNodeRun]:
    return list(
        db.scalars(
            select(SOPNodeRun)
            .where(SOPNodeRun.run_key == run_key)
            .order_by(SOPNodeRun.id)
        ).all()
    )


def instantiate_run(
    db: Session,
    template: SOPTemplate,
    version: SOPVersion,
    *,
    inputs: dict[str, Any],
    actor: str,
    mission_title: str | None,
    mission_priority: str,
    commander: str,
) -> SOPRun:
    if version.status != "PUBLISHED":
        raise ValueError("Only published SOP versions can be executed")
    definition = validate_definition(version.definition)
    validated_inputs = validate_inputs(template, inputs)
    now = utcnow()
    run_key = f"SOPRUN-{uuid4().hex[:12].upper()}"
    mission_key = f"SOP-{uuid4().hex[:12].upper()}"
    mission = Mission(
        mission_key=mission_key,
        title=(mission_title or f"{template.name} · {run_key}")[:200],
        commander=commander[:80],
        status="QUEUED",
        priority=mission_priority,
        progress=0,
        waiting_for=f"SOP {run_key} initialization",
        objective=render_text(template.description or template.name, {
            "input": validated_inputs,
            "run": {"key": run_key},
            "mission": {"key": mission_key},
        })[:600],
        created_at=now,
    )
    run = SOPRun(
        run_key=run_key,
        template_key=template.template_key,
        version_key=version.version_key,
        mission_key=mission_key,
        status="PENDING",
        inputs=validated_inputs,
        outputs={},
        started_by=actor,
        failure_reason=None,
        current_node_key=None,
        started_at=None,
        ended_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(mission)
    db.add(run)
    db.flush()
    for node in definition.nodes:
        db.add(
            SOPNodeRun(
                node_run_key=f"NODE-{uuid4().hex[:14].upper()}",
                run_key=run_key,
                node_key=node.key,
                node_type=node.node_type,
                status="PENDING",
                task_key=None,
                attempt=0,
                input_payload={},
                output_payload={},
                error=None,
                started_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )
        )
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor=actor[:80],
            event_type="SOP_RUN_CREATED",
            message=f"Created {run_key} from {template.template_key} version {version.version_number}."[:800],
            created_at=now,
        )
    )
    sop_event(
        db,
        run,
        "SOP_RUN_CREATED",
        actor,
        f"Created SOP run from {template.name} version {version.version_number}.",
        {"template_key": template.template_key, "version_key": version.version_key, "inputs": validated_inputs},
    )
    db.commit()
    db.refresh(run)
    return run


def node_context(run: SOPRun, mission: Mission, node_runs: dict[str, SOPNodeRun]) -> dict[str, Any]:
    outputs = {
        key: value.output_payload
        for key, value in node_runs.items()
        if not key.startswith("rollback.") and value.output_payload
    }
    return {
        "input": run.inputs or {},
        "run": {"key": run.run_key, "status": run.status},
        "mission": {"key": mission.mission_key, "title": mission.title, "priority": mission.priority},
        "node": outputs,
    }


def dependencies_complete(node: SOPNodeDefinition, node_runs: dict[str, SOPNodeRun]) -> bool:
    return all(
        node_runs.get(key) is not None
        and node_runs[key].status in {"COMPLETED", "SKIPPED", "ROLLED_BACK"}
        for key in node.depends_on
    )


def create_node_task(
    db: Session,
    run: SOPRun,
    mission: Mission,
    node: SOPNodeDefinition,
    node_run: SOPNodeRun,
    all_node_runs: dict[str, SOPNodeRun],
    *,
    rollback_of: str | None = None,
) -> CollaborationTask:
    context = node_context(run, mission, all_node_runs)
    rendered_objective = render_text(node.objective, context)
    rendered_inputs = render_value(node.inputs, context)
    fixed = node.routing_mode == "FIXED"
    target_identity = node.target_identity or ("agent:auto" if not fixed else f"runtime:{node.target_runtime_key}")
    target_runtime = node.target_runtime_key or "auto"
    now = utcnow()
    deadline = now + timedelta(minutes=node.deadline_minutes) if node.deadline_minutes else None
    routing_context = {
        "routing_mode": node.routing_mode if not fixed else "FIXED",
        "required_skills": sorted(set(node.required_skills)),
        "required_capabilities": sorted(set(node.required_capabilities)),
        "required_tools": sorted(set(node.required_tools)),
        "required_clearance": node.required_clearance,
        "preferred_department": node.preferred_department,
        "preferred_runtime_key": node.target_runtime_key,
        "maximum_cost_usd": node.maximum_cost_usd,
        "estimated_tokens": node.estimated_tokens,
        "strict_skills": False,
        "allow_overflow": False,
        "routing": {
            "mode": node.routing_mode if not fixed else "FIXED",
            "status": "QUEUED",
            "attempts": 0,
        },
    }
    task = CollaborationTask(
        task_key=f"TASK-{uuid4().hex[:12].upper()}",
        mission_key=run.mission_key,
        parent_task_key=None,
        title=render_text(node.title, context),
        objective=rendered_objective[:3000],
        source_identity=node.source_identity,
        target_identity=target_identity,
        target_runtime_key=target_runtime,
        status="QUEUED",
        priority=node.priority,
        review_policy=node.review_policy,
        auto_dispatch=node.auto_dispatch,
        depends_on=[],
        inputs=bounded_payload(rendered_inputs, max_chars=9000),
        expected_outputs=render_value(node.expected_outputs, context),
        acceptance_criteria=render_value(node.acceptance_criteria, context),
        context=bounded_payload({
            "sop": {
                "run_key": run.run_key,
                "template_key": run.template_key,
                "version_key": run.version_key,
                "node_key": node_run.node_key,
                "rollback_of": rollback_of,
                "verification_required": node.verification_required,
            },
            **routing_context,
        }, max_chars=12000),
        result={},
        dispatch_key=None,
        attempts=0,
        follow_up_count=0,
        last_progress_at=now,
        next_follow_up_at=None,
        deadline_at=deadline,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    target_mailbox = "service:scheduler" if target_identity == "agent:auto" else target_identity
    create_message(
        db,
        mission_key=run.mission_key,
        task_key=task.task_key,
        message_type="HANDOFF",
        source_identity=node.source_identity,
        target_identity=target_mailbox,
        subject=f"SOP work · {task.title}",
        body=task.objective,
        payload={
            "sop_run_key": run.run_key,
            "sop_node_key": node_run.node_key,
            "required_skills": node.required_skills,
            "required_tools": node.required_tools,
            "verification_required": node.verification_required,
            "rollback_of": rollback_of,
        },
        status="DELIVERED",
        reply_required=True,
        due_at=deadline,
    )
    collaboration_event(
        db,
        task,
        "SOP_TASK_CREATED" if not rollback_of else "SOP_ROLLBACK_TASK_CREATED",
        "service:sop",
        f"Created {task.task_key} for SOP node {node_run.node_key}.",
        {"run_key": run.run_key, "node_key": node_run.node_key, "rollback_of": rollback_of},
    )
    node_run.task_key = task.task_key
    node_run.status = "RUNNING"
    node_run.attempt += 1
    node_run.input_payload = bounded_payload({
        "objective": task.objective,
        "inputs": task.inputs,
        "target_identity": task.target_identity,
        "target_runtime_key": task.target_runtime_key,
    }, max_chars=9000)
    node_run.started_at = now
    node_run.updated_at = now
    run.current_node_key = node_run.node_key
    run.updated_at = now
    return task


def verification_state(task: CollaborationTask) -> str | None:
    verification = (task.result or {}).get("verification")
    if not isinstance(verification, dict):
        return None
    return str(verification.get("status") or "").upper() or None


def sync_task_node(
    db: Session,
    run: SOPRun,
    node: SOPNodeDefinition | None,
    node_run: SOPNodeRun,
) -> None:
    if not node_run.task_key:
        return
    task = db.scalar(
        select(CollaborationTask).where(CollaborationTask.task_key == node_run.task_key)
    )
    if task is None:
        node_run.status = "FAILED"
        node_run.error = "Collaboration task is missing"
        node_run.completed_at = utcnow()
        node_run.updated_at = utcnow()
        return
    node_run.output_payload = bounded_payload(task.result or {}, max_chars=12000)
    if task.status == "COMPLETED":
        required = bool(node.verification_required) if node else False
        verification = verification_state(task)
        if required and verification is None:
            node_run.status = "RUNNING"
            node_run.output_payload = {
                **(node_run.output_payload or {}),
                "sop_waiting_for": "evaluation",
            }
        elif required and verification == "FAIL":
            node_run.status = "FAILED"
            node_run.error = "Evidence evaluation failed"
            node_run.completed_at = utcnow()
        elif required and verification == "WARN":
            node_run.status = "WAITING_APPROVAL"
            node_run.error = "Evidence evaluation warned; human decision required"
        else:
            node_run.status = "ROLLED_BACK" if node_run.node_type == "ROLLBACK" else "COMPLETED"
            node_run.error = None
            node_run.completed_at = utcnow()
    elif task.status in {"REVIEW", "WAITING_APPROVAL"}:
        node_run.status = "WAITING_APPROVAL"
        node_run.error = "Task requires human approval"
    elif task.status in TASK_TERMINAL_FAILURE:
        node_run.status = "FAILED"
        node_run.error = str((task.result or {}).get("error") or f"Task ended as {task.status}")[:2000]
        node_run.completed_at = utcnow()
    else:
        node_run.status = "RUNNING"
    node_run.updated_at = utcnow()


def update_run_progress(db: Session, run: SOPRun, node_runs: list[SOPNodeRun]) -> None:
    mission = db.scalar(select(Mission).where(Mission.mission_key == run.mission_key))
    if mission is None:
        return
    normal = [row for row in node_runs if row.node_type != "ROLLBACK"]
    completed = sum(row.status in {"COMPLETED", "SKIPPED"} for row in normal)
    mission.progress = round(100 * completed / max(1, len(normal)))
    if run.status == "COMPLETED":
        mission.status = "COMPLETED"
        mission.progress = 100
        mission.waiting_for = "SOP completed"
    elif run.status == "WAITING_APPROVAL":
        mission.status = "WAITING_APPROVAL"
        mission.waiting_for = f"Approval for SOP node {run.current_node_key or 'unknown'}"[:180]
    elif run.status == "ROLLING_BACK":
        mission.status = "EXECUTING"
        mission.waiting_for = f"Rolling back SOP {run.run_key}"[:180]
    elif run.status == "FAILED":
        mission.status = "BLOCKED"
        mission.waiting_for = (run.failure_reason or "SOP failed")[:180]
    elif run.status == "CANCELLED":
        mission.status = "BLOCKED"
        mission.waiting_for = "SOP cancelled"
    else:
        mission.status = "EXECUTING"
        mission.waiting_for = f"SOP node {run.current_node_key or 'scheduler'}"[:180]


def rollback_node_definition(original: SOPNodeDefinition) -> SOPNodeDefinition:
    if original.rollback is None:
        raise ValueError("Node does not define rollback")
    rollback = original.rollback
    fixed = bool(rollback.target_runtime_key)
    return SOPNodeDefinition(
        key=f"rollback-{original.key}"[:100],
        title=rollback.title,
        node_type="TASK",
        depends_on=[],
        objective=rollback.objective,
        source_identity="service:sop",
        target_identity=rollback.target_identity or original.target_identity,
        target_runtime_key=rollback.target_runtime_key or original.target_runtime_key,
        routing_mode="FIXED" if fixed else original.routing_mode,
        priority="CRITICAL",
        review_policy="AUTO",
        auto_dispatch=True,
        required_skills=rollback.required_skills or original.required_skills,
        required_capabilities=original.required_capabilities,
        required_tools=rollback.required_tools or original.required_tools,
        required_clearance=original.required_clearance,
        preferred_department=original.preferred_department,
        maximum_cost_usd=original.maximum_cost_usd,
        estimated_tokens=original.estimated_tokens,
        expected_outputs=["rollback evidence", "restored service state"],
        acceptance_criteria=rollback.acceptance_criteria,
        inputs=[],
        deadline_minutes=original.deadline_minutes,
        verification_required=False,
        rollback=None,
    )


def advance_rollback(
    db: Session,
    run: SOPRun,
    definition: SOPDefinition,
    mission: Mission,
    node_runs: list[SOPNodeRun],
) -> None:
    by_key = {row.node_key: row for row in node_runs}
    active = next(
        (row for row in node_runs if row.node_type == "ROLLBACK" and row.status in {"RUNNING", "WAITING_APPROVAL"}),
        None,
    )
    if active is not None:
        sync_task_node(db, run, None, active)
        if active.status == "FAILED":
            run.status = "FAILED"
            run.failure_reason = f"Rollback failed at {active.node_key}: {active.error or 'unknown error'}"
            run.ended_at = utcnow()
            run.updated_at = utcnow()
        return

    order = list(reversed(topological_order(definition)))
    completed_with_rollback = [
        key for key in order
        if by_key.get(key) is not None
        and by_key[key].status == "COMPLETED"
        and next(node for node in definition.nodes if node.key == key).rollback is not None
    ]
    rolled = {
        str((row.input_payload or {}).get("rollback_of"))
        for row in node_runs
        if row.node_type == "ROLLBACK" and row.status == "ROLLED_BACK"
    }
    remaining = [key for key in completed_with_rollback if key not in rolled]
    if not remaining:
        run.status = "FAILED"
        run.ended_at = utcnow()
        run.updated_at = utcnow()
        sop_event(
            db,
            run,
            "SOP_ROLLBACK_COMPLETED",
            "service:sop",
            "Rollback sequence completed; SOP remains failed and requires review.",
            {"failure_reason": run.failure_reason},
            "WARNING",
        )
        return

    original_key = remaining[0]
    original = next(node for node in definition.nodes if node.key == original_key)
    rollback_definition = rollback_node_definition(original)
    now = utcnow()
    rollback_run = SOPNodeRun(
        node_run_key=f"NODE-{uuid4().hex[:14].upper()}",
        run_key=run.run_key,
        node_key=f"rollback.{original_key}"[:100],
        node_type="ROLLBACK",
        status="PENDING",
        task_key=None,
        attempt=0,
        input_payload={"rollback_of": original_key},
        output_payload={},
        error=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(rollback_run)
    db.flush()
    current_rows = {row.node_key: row for row in [*node_runs, rollback_run]}
    create_node_task(
        db,
        run,
        mission,
        rollback_definition,
        rollback_run,
        current_rows,
        rollback_of=original_key,
    )
    rollback_run.input_payload = {
        **(rollback_run.input_payload or {}),
        "rollback_of": original_key,
    }
    sop_event(
        db,
        run,
        "SOP_ROLLBACK_STARTED",
        "service:sop",
        f"Started rollback for completed node {original_key}.",
        {"node_key": original_key, "rollback_node_key": rollback_run.node_key, "task_key": rollback_run.task_key},
        "WARNING",
    )


def collect_outputs(node_runs: list[SOPNodeRun]) -> dict[str, Any]:
    return {
        row.node_key: row.output_payload
        for row in node_runs
        if row.node_type != "ROLLBACK" and row.status == "COMPLETED"
    }


def advance_run(db: Session, run_key: str) -> dict[str, Any]:
    lock_key = f"beezaoffice:sop-run-lock:{run_key}"
    if not redis_client.set(lock_key, "1", nx=True, ex=30):
        return {"run_key": run_key, "action": "locked"}
    try:
        run = get_run(db, run_key)
        if run is None:
            return {"run_key": run_key, "action": "missing"}
        if run.status not in ACTIVE_RUN_STATUSES:
            return {"run_key": run_key, "action": "terminal", "status": run.status}
        version = get_version(db, run.version_key)
        mission = db.scalar(select(Mission).where(Mission.mission_key == run.mission_key))
        if version is None or mission is None:
            run.status = "FAILED"
            run.failure_reason = "SOP version or mission is missing"
            run.ended_at = utcnow()
            run.updated_at = utcnow()
            db.commit()
            return {"run_key": run_key, "action": "failed", "reason": run.failure_reason}
        definition = validate_definition(version.definition)
        nodes_by_definition = {node.key: node for node in definition.nodes}
        rows = run_node_rows(db, run_key)
        rows_by_key = {row.node_key: row for row in rows}
        now = utcnow()
        if run.status == "PENDING":
            run.status = "RUNNING"
            run.started_at = now
            run.updated_at = now
            sop_event(db, run, "SOP_RUN_STARTED", "service:sop", "SOP execution started.")

        if run.status == "ROLLING_BACK":
            advance_rollback(db, run, definition, mission, rows)
            rows = run_node_rows(db, run_key)
            update_run_progress(db, run, rows)
            db.commit()
            return {"run_key": run_key, "action": "rollback", "status": run.status}

        for row in rows:
            if row.node_type == "TASK" and row.status in {"RUNNING", "WAITING_APPROVAL"}:
                sync_task_node(db, run, nodes_by_definition.get(row.node_key), row)

        failed = next((row for row in rows if row.node_type != "ROLLBACK" and row.status == "FAILED"), None)
        if failed is not None:
            run.failure_reason = f"Node {failed.node_key} failed: {failed.error or 'unknown error'}"
            if definition.rollback_on_failure and any(
                node.rollback is not None and rows_by_key.get(node.key) is not None and rows_by_key[node.key].status == "COMPLETED"
                for node in definition.nodes
            ):
                run.status = "ROLLING_BACK"
                run.current_node_key = failed.node_key
                run.updated_at = now
                sop_event(
                    db,
                    run,
                    "SOP_ROLLBACK_REQUIRED",
                    "service:sop",
                    run.failure_reason,
                    {"failed_node": failed.node_key},
                    "ERROR",
                )
                advance_rollback(db, run, definition, mission, rows)
            else:
                run.status = "FAILED"
                run.ended_at = now
                run.updated_at = now
                sop_event(db, run, "SOP_RUN_FAILED", "service:sop", run.failure_reason, {"failed_node": failed.node_key}, "ERROR")
            rows = run_node_rows(db, run_key)
            update_run_progress(db, run, rows)
            db.commit()
            return {"run_key": run_key, "action": "failure", "status": run.status}

        activated: list[str] = []
        for node in definition.nodes:
            row = rows_by_key[node.key]
            if row.status != "PENDING" or not dependencies_complete(node, rows_by_key):
                continue
            if node.node_type == "APPROVAL":
                row.status = "WAITING_APPROVAL"
                row.started_at = now
                row.updated_at = now
                row.input_payload = {"objective": render_text(node.objective, node_context(run, mission, rows_by_key))}
                run.current_node_key = node.key
                activated.append(node.key)
                sop_event(
                    db,
                    run,
                    "SOP_APPROVAL_REQUIRED",
                    "service:sop",
                    f"Approval required for node {node.key}: {node.title}.",
                    {"node_key": node.key, "title": node.title, "objective": row.input_payload["objective"]},
                    "WARNING",
                )
            else:
                create_node_task(db, run, mission, node, row, rows_by_key)
                activated.append(node.key)
                sop_event(
                    db,
                    run,
                    "SOP_NODE_STARTED",
                    "service:sop",
                    f"Started node {node.key}: {node.title}.",
                    {"node_key": node.key, "task_key": row.task_key},
                )

        rows = run_node_rows(db, run_key)
        normal = [row for row in rows if row.node_type != "ROLLBACK"]
        if all(row.status in {"COMPLETED", "SKIPPED"} for row in normal):
            run.status = "COMPLETED"
            run.current_node_key = None
            run.outputs = bounded_payload(collect_outputs(rows), max_chars=30000)
            run.ended_at = utcnow()
            run.updated_at = utcnow()
            sop_event(
                db,
                run,
                "SOP_RUN_COMPLETED",
                "service:sop",
                "All SOP nodes completed successfully.",
                {"outputs": run.outputs},
            )
        elif any(row.status == "WAITING_APPROVAL" for row in normal):
            run.status = "WAITING_APPROVAL"
            waiting = next(row for row in normal if row.status == "WAITING_APPROVAL")
            run.current_node_key = waiting.node_key
            run.updated_at = utcnow()
        else:
            run.status = "RUNNING"
            active = next((row for row in normal if row.status == "RUNNING"), None)
            run.current_node_key = active.node_key if active else run.current_node_key
            run.updated_at = utcnow()
        update_run_progress(db, run, rows)
        db.commit()
        return {"run_key": run_key, "action": "advanced", "activated": activated, "status": run.status}
    finally:
        redis_client.delete(lock_key)


def decide_node(
    db: Session,
    run: SOPRun,
    node_key: str,
    *,
    decision: str,
    actor: str,
    note: str,
) -> SOPNodeRun:
    row = db.scalar(
        select(SOPNodeRun).where(
            SOPNodeRun.run_key == run.run_key,
            SOPNodeRun.node_key == node_key,
        )
    )
    if row is None:
        raise ValueError("SOP node run not found")
    if row.status != "WAITING_APPROVAL":
        raise ValueError(f"Node cannot be decided while status is {row.status}")
    now = utcnow()
    task = None
    if row.task_key:
        task = db.scalar(select(CollaborationTask).where(CollaborationTask.task_key == row.task_key))
    if decision == "approve":
        row.status = "ROLLED_BACK" if row.node_type == "ROLLBACK" else "COMPLETED"
        row.error = None
        row.output_payload = {
            **(row.output_payload or {}),
            "human_decision": {"decision": "approve", "actor": actor, "note": note, "at": now.isoformat()},
        }
        if task and task.status in {"REVIEW", "WAITING_APPROVAL"}:
            task.status = "COMPLETED"
            task.result = {
                **(task.result or {}),
                "human_review": {"decision": "accept", "actor": actor, "note": note, "at": now.isoformat()},
            }
            task.updated_at = now
        event_type = "SOP_NODE_APPROVED"
        severity = "INFO"
    else:
        row.status = "FAILED"
        row.error = note or "Rejected by human decision"
        row.output_payload = {
            **(row.output_payload or {}),
            "human_decision": {"decision": "reject", "actor": actor, "note": note, "at": now.isoformat()},
        }
        if task and task.status in {"REVIEW", "WAITING_APPROVAL"}:
            task.status = "FAILED"
            task.result = {
                **(task.result or {}),
                "human_review": {"decision": "reject", "actor": actor, "note": note, "at": now.isoformat()},
            }
            task.updated_at = now
        event_type = "SOP_NODE_REJECTED"
        severity = "ERROR"
    row.completed_at = now
    row.updated_at = now
    run.status = "RUNNING"
    run.current_node_key = node_key
    run.updated_at = now
    sop_event(
        db,
        run,
        event_type,
        actor,
        note or f"Node {node_key} {decision}d.",
        {"node_key": node_key, "task_key": row.task_key, "decision": decision},
        severity,
    )
    db.commit()
    db.refresh(row)
    return row


def cancel_run(db: Session, run: SOPRun, *, actor: str, note: str) -> SOPRun:
    if run.status not in ACTIVE_RUN_STATUSES:
        raise ValueError(f"SOP run cannot be cancelled from {run.status}")
    now = utcnow()
    for row in run_node_rows(db, run.run_key):
        if row.status in {"PENDING", "READY"}:
            row.status = "CANCELLED"
            row.completed_at = now
            row.updated_at = now
        elif row.status in {"RUNNING", "WAITING_APPROVAL"}:
            row.output_payload = {
                **(row.output_payload or {}),
                "cancellation_requested": {"actor": actor, "note": note, "at": now.isoformat()},
            }
            row.updated_at = now
    run.status = "CANCELLED"
    run.failure_reason = note or "Cancelled by operator"
    run.ended_at = now
    run.updated_at = now
    sop_event(
        db,
        run,
        "SOP_RUN_CANCELLED",
        actor,
        run.failure_reason,
        {"note": note},
        "WARNING",
    )
    update_run_progress(db, run, run_node_rows(db, run.run_key))
    db.commit()
    db.refresh(run)
    return run


def sop_stats(db: Session) -> dict[str, Any]:
    templates = list(db.scalars(select(SOPTemplate)).all())
    runs = list(db.scalars(select(SOPRun)).all())
    run_counts: dict[str, int] = {}
    for run in runs:
        run_counts[run.status] = run_counts.get(run.status, 0) + 1
    return {
        "templates": len(templates),
        "published_templates": sum(item.status == "PUBLISHED" for item in templates),
        "versions": db.query(SOPVersion).count(),
        "runs": len(runs),
        "run_statuses": dict(sorted(run_counts.items())),
        "active_runs": sum(run.status in ACTIVE_RUN_STATUSES for run in runs),
        "completed_runs": run_counts.get("COMPLETED", 0),
        "failed_runs": run_counts.get("FAILED", 0),
    }


def sop_tick() -> dict[str, int]:
    processed = completed = failed = waiting = 0
    with SessionLocal() as db:
        keys = list(
            db.scalars(
                select(SOPRun.run_key)
                .where(SOPRun.status.in_(ACTIVE_RUN_STATUSES))
                .order_by(SOPRun.updated_at)
                .limit(SOP_BATCH)
            ).all()
        )
        for key in keys:
            result = advance_run(db, key)
            processed += 1
            completed += result.get("status") == "COMPLETED"
            failed += result.get("status") == "FAILED"
            waiting += result.get("status") == "WAITING_APPROVAL"
    return {"processed": processed, "completed": completed, "failed": failed, "waiting": waiting}


async def sop_worker() -> None:
    while True:
        try:
            result = await asyncio.to_thread(sop_tick)
            redis_client.hset(
                "beezaoffice:sop-worker",
                mapping={
                    "status": "online",
                    "last_tick_at": utcnow().isoformat(),
                    "last_processed": str(result["processed"]),
                    "last_completed": str(result["completed"]),
                    "last_failed": str(result["failed"]),
                    "last_waiting": str(result["waiting"]),
                    "interval_seconds": str(SOP_INTERVAL),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            redis_client.hset(
                "beezaoffice:sop-worker",
                mapping={
                    "status": "degraded",
                    "last_tick_at": utcnow().isoformat(),
                    "last_error": str(exc)[:500],
                },
            )
        await asyncio.sleep(SOP_INTERVAL)
