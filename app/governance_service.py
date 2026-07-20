from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from governance_models import (
    ApprovalRequest,
    AuditRecord,
    BudgetLedger,
    Department,
    GovernanceIdentity,
    GovernanceRole,
    PolicyRule,
    RoleBinding,
    SystemControl,
    Tenant,
)
from main import Agent, SessionLocal, bounded_payload, utcnow

DEFAULT_IDENTITY = os.getenv("BEEZA_DEFAULT_IDENTITY", "human:owner").strip() or "human:owner"
GOVERNANCE_ENFORCED = os.getenv("BEEZA_GOVERNANCE_ENFORCED", "true").lower() not in {
    "0", "false", "no", "off",
}
APPROVAL_TTL_MINUTES = max(1, int(os.getenv("BEEZA_APPROVAL_TTL_MINUTES", "60")))

request_identity: ContextVar[str] = ContextVar("beeza_request_identity", default="service:runtime")
request_id: ContextVar[str] = ContextVar("beeza_request_id", default="")
request_risk: ContextVar[str] = ContextVar("beeza_request_risk", default="NORMAL")
request_classification: ContextVar[str] = ContextVar("beeza_request_classification", default="INTERNAL")
request_approval_key: ContextVar[str] = ContextVar("beeza_request_approval_key", default="")
request_estimated_cost: ContextVar[float] = ContextVar("beeza_request_estimated_cost", default=0.0)

CLEARANCE_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}
RISK_RANK = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "CRITICAL": 3}
EXECUTION_ACTIONS = {
    "runtime:dispatch",
    "runtime:stop",
    "runtime:approval",
    "handoff:create",
    "task:control",
    "meeting:start",
    "meeting:control",
    "meeting:decide",
}

ROUTE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/api/missions$"), "mission:create"),
    ("POST", re.compile(r"^/api/runtimes/[^/]+/probe$"), "runtime:probe"),
    ("POST", re.compile(r"^/api/runtimes/[^/]+/dispatch$"), "runtime:dispatch"),
    ("POST", re.compile(r"^/api/runtime-dispatches/[^/]+/sync$"), "runtime:sync"),
    ("POST", re.compile(r"^/api/runtime-dispatches/[^/]+/stop$"), "runtime:stop"),
    ("POST", re.compile(r"^/api/runtime-dispatches/[^/]+/approval$"), "runtime:approval"),
    ("POST", re.compile(r"^/api/missions/[^/]+/handoffs$"), "handoff:create"),
    ("POST", re.compile(r"^/api/collaboration/tasks/[^/]+/actions$"), "task:control"),
    ("POST", re.compile(r"^/api/collaboration/tasks/[^/]+/review$"), "task:review"),
    ("POST", re.compile(r"^/api/missions/[^/]+/messages$"), "message:create"),
    ("POST", re.compile(r"^/api/collaboration/tick$"), "task:control"),
    ("POST", re.compile(r"^/api/missions/[^/]+/meetings$"), "meeting:create"),
    ("POST", re.compile(r"^/api/meetings/[^/]+/start$"), "meeting:start"),
    ("POST", re.compile(r"^/api/meetings/[^/]+/tick$"), "meeting:control"),
    ("POST", re.compile(r"^/api/meetings/[^/]+/cancel$"), "meeting:control"),
    ("POST", re.compile(r"^/api/meetings/[^/]+/decision$"), "meeting:decide"),
    ("POST", re.compile(r"^/api/meeting-worker/tick$"), "meeting:control"),
    ("POST", re.compile(r"^/api/governance/identities$"), "governance:identity:write"),
    ("POST", re.compile(r"^/api/governance/bindings$"), "governance:role:write"),
    ("POST", re.compile(r"^/api/governance/policies$"), "governance:policy:write"),
    ("POST", re.compile(r"^/api/governance/approvals$"), "approval:request"),
    ("POST", re.compile(r"^/api/governance/approvals/[^/]+/decision$"), "approval:decide"),
    ("POST", re.compile(r"^/api/governance/kill-switch$"), "governance:kill-switch"),
    ("POST", re.compile(r"^/api/governance/budget/charge$"), "budget:charge"),
]


def permission_for_request(method: str, path: str) -> str:
    upper = method.upper()
    for expected_method, pattern, permission in ROUTE_RULES:
        if expected_method == upper and pattern.match(path):
            return permission
    if upper in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
        return "api:write"
    return "api:read"


def mission_from_path(path: str) -> str | None:
    match = re.search(r"/api/missions/([^/]+)", path)
    return match.group(1) if match else None


def role_permissions(db: Session, identity_key: str, mission_key: str | None = None) -> list[str]:
    bindings = db.scalars(
        select(RoleBinding).where(RoleBinding.identity_key == identity_key)
    ).all()
    role_keys: list[str] = []
    for binding in bindings:
        if binding.scope_type == "GLOBAL":
            role_keys.append(binding.role_key)
        elif binding.scope_type == "MISSION" and mission_key and binding.scope_key == mission_key:
            role_keys.append(binding.role_key)
        elif binding.scope_type in {"TENANT", "DEPARTMENT"}:
            role_keys.append(binding.role_key)
    if not role_keys:
        return []
    roles = db.scalars(
        select(GovernanceRole).where(GovernanceRole.role_key.in_(role_keys))
    ).all()
    permissions: list[str] = []
    for role in roles:
        permissions.extend(role.permissions or [])
    return sorted(set(permissions))


def permission_matches(granted: str, required: str) -> bool:
    return granted == "*" or fnmatch.fnmatchcase(required, granted)


def has_permission(db: Session, identity_key: str, required: str, mission_key: str | None = None) -> bool:
    return any(
        permission_matches(granted, required)
        for granted in role_permissions(db, identity_key, mission_key)
    )


def get_control(db: Session, control_key: str = "runtime_execution_enabled") -> SystemControl | None:
    return db.scalar(
        select(SystemControl).where(SystemControl.control_key == control_key)
    )


def execution_enabled(db: Session) -> bool:
    row = get_control(db)
    return True if row is None else bool(row.enabled)


def identity_view(row: GovernanceIdentity, permissions: list[str] | None = None) -> dict[str, Any]:
    return {
        "key": row.identity_key,
        "tenant_key": row.tenant_key,
        "type": row.identity_type,
        "name": row.display_name,
        "department_key": row.department_key,
        "status": row.status,
        "clearance": row.clearance,
        "daily_budget_usd": row.daily_budget_usd,
        "monthly_budget_usd": row.monthly_budget_usd,
        "attributes": row.attributes,
        "permissions": permissions or [],
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def approval_view(row: ApprovalRequest) -> dict[str, Any]:
    return {
        "key": row.approval_key,
        "action": row.action,
        "requester_identity": row.requester_identity,
        "target": row.target,
        "mission_key": row.mission_key,
        "risk_level": row.risk_level,
        "reason": row.reason,
        "payload_hash": row.payload_hash,
        "status": row.status,
        "requested_at": row.requested_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "used_at": row.used_at.isoformat() if row.used_at else None,
    }


def policy_view(row: PolicyRule) -> dict[str, Any]:
    return {
        "key": row.policy_key,
        "name": row.name,
        "action_pattern": row.action_pattern,
        "effect": row.effect,
        "risk_levels": row.risk_levels,
        "minimum_clearance": row.minimum_clearance,
        "maximum_cost_usd": row.maximum_cost_usd,
        "priority": row.priority,
        "enabled": row.enabled,
        "conditions": row.conditions,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def budget_totals(db: Session, identity_key: str, now: datetime | None = None) -> dict[str, float]:
    current = now or utcnow()
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def total_since(start: datetime) -> float:
        charges = db.scalar(
            select(func.coalesce(func.sum(BudgetLedger.amount_usd), 0.0)).where(
                BudgetLedger.identity_key == identity_key,
                BudgetLedger.created_at >= start,
                BudgetLedger.entry_type.in_(["RESERVE", "CHARGE", "ADJUST"]),
            )
        )
        releases = db.scalar(
            select(func.coalesce(func.sum(BudgetLedger.amount_usd), 0.0)).where(
                BudgetLedger.identity_key == identity_key,
                BudgetLedger.created_at >= start,
                BudgetLedger.entry_type == "RELEASE",
            )
        )
        return max(0.0, float(charges or 0.0) - float(releases or 0.0))

    return {"daily": total_since(day_start), "monthly": total_since(month_start)}


def find_valid_approval(
    db: Session,
    approval_key: str,
    identity_key: str,
    action: str,
) -> ApprovalRequest | None:
    if not approval_key:
        return None
    row = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.approval_key == approval_key,
            ApprovalRequest.requester_identity == identity_key,
            ApprovalRequest.action == action,
        )
    )
    if row is None or row.status != "APPROVED" or row.expires_at <= utcnow():
        return None
    return row


def evaluate_authorization(
    db: Session,
    *,
    identity_key: str,
    action: str,
    mission_key: str | None = None,
    risk_level: str = "NORMAL",
    data_classification: str = "INTERNAL",
    estimated_cost_usd: float = 0.0,
    approval_key: str = "",
) -> dict[str, Any]:
    if not GOVERNANCE_ENFORCED:
        return {"allowed": True, "reason": "Governance enforcement disabled"}
    identity = db.scalar(
        select(GovernanceIdentity).where(
            GovernanceIdentity.identity_key == identity_key
        )
    )
    if identity is None:
        return {"allowed": False, "reason": f"Unknown identity {identity_key}"}
    if identity.status != "ACTIVE":
        return {"allowed": False, "reason": f"Identity is {identity.status.lower()}"}
    if not has_permission(db, identity_key, action, mission_key):
        return {"allowed": False, "reason": f"Missing permission {action}"}
    if action in EXECUTION_ACTIONS and not execution_enabled(db):
        control = get_control(db)
        return {
            "allowed": False,
            "reason": f"Execution kill switch is active: {control.reason if control else 'disabled'}",
            "kill_switch": True,
        }

    classification = data_classification.upper()
    clearance = identity.clearance.upper()
    if CLEARANCE_RANK.get(clearance, 0) < CLEARANCE_RANK.get(classification, 1):
        return {
            "allowed": False,
            "reason": f"{clearance} clearance cannot access {classification} data",
        }

    cost = max(0.0, float(estimated_cost_usd or 0.0))
    if cost:
        totals = budget_totals(db, identity_key)
        if totals["daily"] + cost > identity.daily_budget_usd:
            return {
                "allowed": False,
                "reason": "Daily identity budget would be exceeded",
                "budget": {**totals, "estimate": cost, "daily_limit": identity.daily_budget_usd},
            }
        if totals["monthly"] + cost > identity.monthly_budget_usd:
            return {
                "allowed": False,
                "reason": "Monthly identity budget would be exceeded",
                "budget": {**totals, "estimate": cost, "monthly_limit": identity.monthly_budget_usd},
            }

    approval_required = False
    matched_policies: list[str] = []
    rules = db.scalars(
        select(PolicyRule)
        .where(PolicyRule.enabled.is_(True))
        .order_by(PolicyRule.priority, PolicyRule.id)
    ).all()
    for rule in rules:
        if not fnmatch.fnmatchcase(action, rule.action_pattern):
            continue
        if rule.risk_levels and risk_level.upper() not in {item.upper() for item in rule.risk_levels}:
            continue
        if CLEARANCE_RANK.get(clearance, 0) < CLEARANCE_RANK.get(rule.minimum_clearance, 0):
            continue
        if rule.maximum_cost_usd is not None and cost <= rule.maximum_cost_usd:
            continue
        matched_policies.append(rule.policy_key)
        if rule.effect == "DENY":
            return {
                "allowed": False,
                "reason": f"Denied by policy {rule.name}",
                "matched_policies": matched_policies,
            }
        if rule.effect == "APPROVAL":
            approval_required = True

    if RISK_RANK.get(risk_level.upper(), 1) >= RISK_RANK["HIGH"] and action in {
        "runtime:dispatch", "task:control", "meeting:decide",
    }:
        approval_required = True

    approval = find_valid_approval(db, approval_key, identity_key, action)
    if approval_required and approval is None:
        return {
            "allowed": False,
            "reason": "Approved governance request required",
            "approval_required": True,
            "matched_policies": matched_policies,
        }
    return {
        "allowed": True,
        "reason": "Allowed by RBAC and policy",
        "approval_key": approval.approval_key if approval else None,
        "matched_policies": matched_policies,
        "identity": identity_view(identity, role_permissions(db, identity_key, mission_key)),
    }


def create_approval(
    db: Session,
    *,
    action: str,
    requester_identity: str,
    target: str,
    mission_key: str | None,
    risk_level: str,
    reason: str,
    payload_hash: str = "",
    expires_in_minutes: int | None = None,
) -> ApprovalRequest:
    now = utcnow()
    row = ApprovalRequest(
        approval_key=f"APR-{uuid4().hex[:14].upper()}",
        action=action,
        requester_identity=requester_identity,
        target=target[:500],
        mission_key=mission_key,
        risk_level=risk_level.upper(),
        reason=reason[:2000],
        payload_hash=payload_hash[:128],
        status="PENDING",
        requested_at=now,
        expires_at=now + timedelta(minutes=expires_in_minutes or APPROVAL_TTL_MINUTES),
        decided_by=None,
        decision_note=None,
        decided_at=None,
        used_at=None,
    )
    db.add(row)
    db.flush()
    return row


def mark_approval_used(db: Session, approval_key: str | None) -> None:
    if not approval_key:
        return
    row = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.approval_key == approval_key)
    )
    if row and row.status == "APPROVED":
        row.status = "USED"
        row.used_at = utcnow()


def record_budget_entry(
    db: Session,
    *,
    identity_key: str,
    action: str,
    amount_usd: float,
    entry_type: str = "CHARGE",
    mission_key: str | None = None,
    reference_key: str | None = None,
    details: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> BudgetLedger:
    row = BudgetLedger(
        ledger_key=f"LED-{uuid4().hex[:14].upper()}",
        identity_key=identity_key,
        mission_key=mission_key,
        action=action,
        entry_type=entry_type,
        amount_usd=round(float(amount_usd), 6),
        reference_key=reference_key,
        details=bounded_payload(details or {}),
        created_by=created_by or identity_key,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def append_audit(
    db: Session,
    *,
    audit_request_id: str,
    identity_key: str,
    action: str,
    method: str,
    path: str,
    outcome: str,
    status_code: int,
    resource: str = "",
    detail: dict[str, Any] | None = None,
    source_ip: str = "",
    user_agent: str = "",
) -> AuditRecord:
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(74100601)"))
    except Exception:
        pass
    previous = db.scalar(select(AuditRecord).order_by(AuditRecord.id.desc()).limit(1))
    previous_hash = previous.record_hash if previous else "GENESIS"
    created_at = utcnow()
    canonical = json.dumps(
        {
            "request_id": audit_request_id,
            "identity_key": identity_key,
            "action": action,
            "method": method,
            "path": path,
            "resource": resource,
            "outcome": outcome,
            "status_code": status_code,
            "detail": bounded_payload(detail or {}, max_chars=6000),
            "source_ip": source_ip,
            "user_agent": user_agent,
            "previous_hash": previous_hash,
            "created_at": created_at.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    record_hash = hashlib.sha256(canonical.encode()).hexdigest()
    row = AuditRecord(
        audit_key=f"AUD-{uuid4().hex[:14].upper()}",
        request_id=audit_request_id,
        identity_key=identity_key,
        action=action,
        method=method,
        path=path[:1000],
        resource=resource[:500],
        outcome=outcome,
        status_code=status_code,
        detail=bounded_payload(detail or {}, max_chars=6000),
        source_ip=source_ip[:100],
        user_agent=user_agent[:500],
        previous_hash=previous_hash,
        record_hash=record_hash,
        created_at=created_at,
    )
    db.add(row)
    db.flush()
    return row


def audit_view(row: AuditRecord) -> dict[str, Any]:
    return {
        "key": row.audit_key,
        "request_id": row.request_id,
        "identity_key": row.identity_key,
        "action": row.action,
        "method": row.method,
        "path": row.path,
        "resource": row.resource,
        "outcome": row.outcome,
        "status_code": row.status_code,
        "detail": row.detail,
        "source_ip": row.source_ip,
        "previous_hash": row.previous_hash,
        "record_hash": row.record_hash,
        "created_at": row.created_at.isoformat(),
    }


def verify_audit_chain(db: Session, limit: int = 5000) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(AuditRecord).order_by(AuditRecord.id).limit(limit)
        ).all()
    )
    previous_hash = "GENESIS"
    broken_at: str | None = None
    for row in rows:
        if row.previous_hash != previous_hash:
            broken_at = row.audit_key
            break
        canonical = json.dumps(
            {
                "request_id": row.request_id,
                "identity_key": row.identity_key,
                "action": row.action,
                "method": row.method,
                "path": row.path,
                "resource": row.resource,
                "outcome": row.outcome,
                "status_code": row.status_code,
                "detail": row.detail,
                "source_ip": row.source_ip,
                "user_agent": row.user_agent,
                "previous_hash": row.previous_hash,
                "created_at": row.created_at.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        if expected != row.record_hash:
            broken_at = row.audit_key
            break
        previous_hash = row.record_hash
    return {
        "valid": broken_at is None,
        "checked": len(rows),
        "broken_at": broken_at,
        "head_hash": previous_hash,
        "truncated": len(rows) >= limit,
    }


def machine_action_allowed(identity_key: str, action: str, mission_key: str | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        return evaluate_authorization(
            db,
            identity_key=identity_key,
            action=action,
            mission_key=mission_key,
            risk_level=request_risk.get(),
            data_classification=request_classification.get(),
            estimated_cost_usd=request_estimated_cost.get(),
            approval_key=request_approval_key.get(),
        )


def seed_governance(db: Session) -> None:
    now = utcnow()
    tenant = db.scalar(select(Tenant).where(Tenant.tenant_key == "tenant:beeza"))
    if tenant is None:
        db.add(
            Tenant(
                tenant_key="tenant:beeza",
                name="BeezaOffice",
                status="ACTIVE",
                data_region="sovereign/on-premises",
                created_at=now,
                updated_at=now,
            )
        )

    departments = {
        "dept:executive": ("Executive", None, "HIGH"),
        "dept:operations": ("Operations", "dept:executive", "CRITICAL"),
        "dept:data": ("Data", "dept:operations", "HIGH"),
        "dept:quality": ("Quality", "dept:operations", "HIGH"),
        "dept:finance": ("Finance", "dept:executive", "HIGH"),
        "dept:support": ("Support", "dept:executive", "NORMAL"),
        "dept:people": ("People", "dept:executive", "HIGH"),
        "dept:legal": ("Legal", "dept:executive", "HIGH"),
        "dept:procurement": ("Procurement", "dept:finance", "HIGH"),
        "dept:marketing": ("Marketing", "dept:executive", "NORMAL"),
        "dept:platform": ("AI Platform", "dept:operations", "CRITICAL"),
    }
    for key, (name, parent, risk) in departments.items():
        if db.scalar(select(Department.id).where(Department.department_key == key)) is None:
            db.add(
                Department(
                    department_key=key,
                    tenant_key="tenant:beeza",
                    name=name,
                    parent_department_key=parent,
                    risk_tier=risk,
                    created_at=now,
                    updated_at=now,
                )
            )

    roles = {
        "role:owner": ("Owner", "Full platform authority", ["*"]),
        "role:executive": (
            "Executive",
            "Mission, decision, approval and audit authority",
            [
                "api:read", "governance:read", "audit:read", "approval:*",
                "mission:*", "runtime:*", "handoff:*", "task:*", "message:*",
                "meeting:*", "budget:read",
            ],
        ),
        "role:manager": (
            "Manager",
            "Creates and coordinates missions, handoffs and meetings",
            [
                "api:read", "governance:read", "approval:request", "mission:create",
                "runtime:probe", "runtime:dispatch", "runtime:sync", "handoff:create",
                "task:control", "task:review", "message:create", "meeting:*",
                "budget:read",
            ],
        ),
        "role:operator": (
            "Operator",
            "Runs approved operational work",
            [
                "api:read", "governance:read", "approval:request", "mission:create",
                "runtime:probe", "runtime:dispatch", "runtime:sync", "runtime:stop",
                "runtime:approval", "handoff:create", "task:control", "task:review",
                "message:create", "meeting:create", "meeting:start", "meeting:control",
                "budget:read",
            ],
        ),
        "role:auditor": (
            "Auditor",
            "Read-only governance and evidence access",
            ["api:read", "governance:read", "audit:read", "budget:read"],
        ),
        "role:agent": (
            "Agent",
            "Typed collaboration without platform administration",
            ["api:read", "handoff:create", "message:create", "meeting:participate"],
        ),
        "role:service": (
            "Service",
            "Background worker execution permissions",
            [
                "api:read", "runtime:dispatch", "runtime:sync", "handoff:create",
                "task:control", "message:create", "meeting:turn", "budget:charge",
            ],
        ),
        "role:runtime": (
            "Runtime",
            "Runtime callback and event identity",
            ["api:read", "runtime:callback", "message:create"],
        ),
    }
    for key, (name, description, permissions) in roles.items():
        row = db.scalar(select(GovernanceRole).where(GovernanceRole.role_key == key))
        if row is None:
            db.add(
                GovernanceRole(
                    role_key=key,
                    name=name,
                    description=description,
                    permissions=permissions,
                    system_role=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.permissions = permissions
            row.description = description
            row.updated_at = now

    identity_specs: dict[str, tuple[str, str, str | None, str, float, float, str]] = {
        "human:owner": ("Beeza Owner", "HUMAN", "dept:executive", "RESTRICTED", 1000.0, 30000.0, "role:owner"),
        "human:operator": ("Beeza Operator", "HUMAN", "dept:operations", "CONFIDENTIAL", 500.0, 10000.0, "role:operator"),
        "human:auditor": ("Beeza Auditor", "HUMAN", "dept:quality", "RESTRICTED", 0.0, 0.0, "role:auditor"),
        "agent:Beeza Commander": ("Beeza Commander", "AGENT", "dept:executive", "CONFIDENTIAL", 100.0, 3000.0, "role:manager"),
        "agent:Beeza Moderator": ("Beeza Moderator", "AGENT", "dept:executive", "CONFIDENTIAL", 50.0, 1500.0, "role:manager"),
        "service:runtime": ("Runtime Dispatch Service", "SERVICE", "dept:platform", "RESTRICTED", 1000.0, 30000.0, "role:service"),
        "service:collaboration": ("Collaboration Worker", "SERVICE", "dept:platform", "RESTRICTED", 1000.0, 30000.0, "role:service"),
        "service:meeting": ("Meeting Worker", "SERVICE", "dept:platform", "RESTRICTED", 1000.0, 30000.0, "role:service"),
    }
    agent_department_map = {
        "Executive": "dept:executive", "Operations": "dept:operations", "Data": "dept:data",
        "Quality": "dept:quality", "Finance": "dept:finance", "Support": "dept:support",
        "People": "dept:people", "Legal": "dept:legal", "Procurement": "dept:procurement",
        "Marketing": "dept:marketing",
    }
    for agent in db.scalars(select(Agent)).all():
        identity_specs.setdefault(
            f"agent:{agent.name}",
            (
                agent.name,
                "AGENT",
                agent_department_map.get(agent.department, "dept:platform"),
                "CONFIDENTIAL" if agent.department in {"Operations", "Finance", "Legal", "People"} else "INTERNAL",
                50.0,
                1000.0,
                "role:agent",
            ),
        )
    for runtime_key in ("openclaw", "cherryagent", "hermes", "thclaws"):
        identity_specs[f"runtime:{runtime_key}"] = (
            f"{runtime_key} runtime",
            "RUNTIME",
            "dept:platform",
            "RESTRICTED",
            500.0,
            10000.0,
            "role:runtime",
        )

    for key, (name, identity_type, department_key, clearance, daily, monthly, role_key) in identity_specs.items():
        row = db.scalar(
            select(GovernanceIdentity).where(GovernanceIdentity.identity_key == key)
        )
        if row is None:
            row = GovernanceIdentity(
                identity_key=key,
                tenant_key="tenant:beeza",
                identity_type=identity_type,
                display_name=name,
                department_key=department_key,
                status="ACTIVE",
                clearance=clearance,
                daily_budget_usd=daily,
                monthly_budget_usd=monthly,
                attributes={"seeded": True},
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        binding = db.scalar(
            select(RoleBinding).where(
                RoleBinding.identity_key == key,
                RoleBinding.role_key == role_key,
                RoleBinding.scope_type == "GLOBAL",
            )
        )
        if binding is None:
            db.add(
                RoleBinding(
                    binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                    identity_key=key,
                    role_key=role_key,
                    scope_type="GLOBAL",
                    scope_key="*",
                    created_by="system:bootstrap",
                    created_at=now,
                )
            )

    policy_specs = [
        (
            "policy:high-risk-approval",
            "High-risk execution requires approval",
            "runtime:dispatch",
            "APPROVAL",
            ["HIGH", "CRITICAL"],
            "CONFIDENTIAL",
            None,
            10,
        ),
        (
            "policy:critical-decision-approval",
            "Critical meeting decisions require approval",
            "meeting:decide",
            "APPROVAL",
            ["CRITICAL"],
            "CONFIDENTIAL",
            None,
            20,
        ),
        (
            "policy:large-cost-approval",
            "Large estimated operations require approval",
            "*",
            "APPROVAL",
            [],
            "INTERNAL",
            100.0,
            30,
        ),
    ]
    for key, name, pattern, effect, risks, clearance, maximum_cost, priority in policy_specs:
        row = db.scalar(select(PolicyRule).where(PolicyRule.policy_key == key))
        if row is None:
            db.add(
                PolicyRule(
                    policy_key=key,
                    name=name,
                    action_pattern=pattern,
                    effect=effect,
                    risk_levels=risks,
                    minimum_clearance=clearance,
                    maximum_cost_usd=maximum_cost,
                    priority=priority,
                    enabled=True,
                    conditions={},
                    created_by="system:bootstrap",
                    created_at=now,
                    updated_at=now,
                )
            )

    control = get_control(db)
    if control is None:
        db.add(
            SystemControl(
                control_key="runtime_execution_enabled",
                enabled=True,
                reason="Initial governance bootstrap",
                changed_by="system:bootstrap",
                updated_at=now,
            )
        )
    db.commit()
