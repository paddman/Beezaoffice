from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_service import DEFAULT_TENANT
from main import utcnow
from pilot_models import (
    PILOT_GATES,
    PilotGateEvidence,
    PilotProgram,
    gate_view,
    pilot_view,
)
from release_version import APP_VERSION

DEFAULT_ACCEPTANCE_CRITERIA: dict[str, Any] = {
    "minimum_runtime_success_rate": 0.99,
    "maximum_api_error_rate": 0.01,
    "maximum_p95_latency_ms": 1500,
    "minimum_security_score": 90,
    "backup_restore_required": True,
    "customer_signoff_required": True,
}


def evidence_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def seed_pilot(db: Session) -> PilotProgram:
    row = db.scalar(
        select(PilotProgram).where(
            PilotProgram.tenant_key == DEFAULT_TENANT,
            PilotProgram.target_version == APP_VERSION,
        )
    )
    now = utcnow()
    if row is None:
        row = PilotProgram(
            pilot_key=f"PILOT-{APP_VERSION.replace('.', '')}-INTERNAL",
            tenant_key=DEFAULT_TENANT,
            customer_name="BeezaOffice Internal Pilot",
            environment="pilot",
            target_version=APP_VERSION,
            status="DRAFT",
            owner_identity="human:owner",
            runtime_keys=["openclaw", "cherryagent", "hermes", "thclaws"],
            acceptance_criteria=DEFAULT_ACCEPTANCE_CRITERIA,
            notes="Internal release-validation program. External customer acceptance must be recorded separately.",
            accepted_by=None,
            accepted_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
    existing = {
        item.gate_key: item
        for item in db.scalars(
            select(PilotGateEvidence).where(PilotGateEvidence.pilot_key == row.pilot_key)
        ).all()
    }
    for gate_key in PILOT_GATES:
        if gate_key in existing:
            continue
        payload = {
            "pilot_key": row.pilot_key,
            "gate_key": gate_key,
            "status": "PENDING",
            "source": "SYSTEM",
            "summary": "Awaiting evidence",
            "metrics": {},
            "artifact_ref": "",
        }
        db.add(
            PilotGateEvidence(
                evidence_key=f"EVID-{uuid4().hex[:16].upper()}",
                pilot_key=row.pilot_key,
                gate_key=gate_key,
                status="PENDING",
                source="SYSTEM",
                summary="Awaiting evidence",
                metrics={},
                artifact_ref="",
                integrity_hash=evidence_hash(payload),
                recorded_by="system:pilot",
                started_at=None,
                completed_at=None,
                updated_at=now,
            )
        )
    db.commit()
    db.refresh(row)
    return row


def gates_for(db: Session, pilot_key: str) -> list[PilotGateEvidence]:
    return list(
        db.scalars(
            select(PilotGateEvidence)
            .where(PilotGateEvidence.pilot_key == pilot_key)
            .order_by(PilotGateEvidence.gate_key)
        ).all()
    )


def compute_status(row: PilotProgram, gates: list[PilotGateEvidence]) -> str:
    if row.status in {"ACCEPTED", "REJECTED", "CANCELLED"}:
        return row.status
    statuses = {gate.status for gate in gates}
    if statuses & {"FAIL", "BLOCKED"}:
        return "BLOCKED"
    if "RUNNING" in statuses:
        return "RUNNING"
    required = {gate.gate_key: gate.status for gate in gates if gate.gate_key in PILOT_GATES}
    if required and all(required.get(key) == "PASS" for key in PILOT_GATES):
        return "AWAITING_ACCEPTANCE"
    if any(value == "PASS" for value in required.values()):
        return "RUNNING"
    return "READY" if gates else "DRAFT"


def reconcile_pilot(db: Session, row: PilotProgram) -> PilotProgram:
    status = compute_status(row, gates_for(db, row.pilot_key))
    if row.status != status:
        row.status = status
        row.updated_at = utcnow()
        db.commit()
        db.refresh(row)
    return row


def upsert_gate(
    db: Session,
    row: PilotProgram,
    gate_key: str,
    status: str,
    source: str,
    summary: str,
    metrics: dict[str, Any],
    artifact_ref: str,
    actor: str,
    started_at,
    completed_at,
) -> PilotGateEvidence:
    if gate_key not in PILOT_GATES:
        raise ValueError(f"Unknown pilot gate: {gate_key}")
    evidence = db.scalar(
        select(PilotGateEvidence).where(
            PilotGateEvidence.pilot_key == row.pilot_key,
            PilotGateEvidence.gate_key == gate_key,
        )
    )
    now = utcnow()
    payload = {
        "pilot_key": row.pilot_key,
        "gate_key": gate_key,
        "status": status,
        "source": source,
        "summary": summary,
        "metrics": metrics,
        "artifact_ref": artifact_ref,
        "recorded_by": actor,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    digest = evidence_hash(payload)
    if evidence is None:
        evidence = PilotGateEvidence(
            evidence_key=f"EVID-{uuid4().hex[:16].upper()}",
            pilot_key=row.pilot_key,
            gate_key=gate_key,
            status=status,
            source=source,
            summary=summary,
            metrics=metrics,
            artifact_ref=artifact_ref,
            integrity_hash=digest,
            recorded_by=actor,
            started_at=started_at,
            completed_at=completed_at,
            updated_at=now,
        )
        db.add(evidence)
    else:
        evidence.status = status
        evidence.source = source
        evidence.summary = summary
        evidence.metrics = metrics
        evidence.artifact_ref = artifact_ref
        evidence.integrity_hash = digest
        evidence.recorded_by = actor
        evidence.started_at = started_at
        evidence.completed_at = completed_at
        evidence.updated_at = now
    row.updated_at = now
    if row.status in {"ACCEPTED", "REJECTED"}:
        row.status = "RUNNING"
        row.accepted_by = None
        row.accepted_at = None
    db.commit()
    db.refresh(evidence)
    reconcile_pilot(db, row)
    return evidence


def readiness_view(db: Session, row: PilotProgram) -> dict[str, Any]:
    row = reconcile_pilot(db, row)
    gates = gates_for(db, row.pilot_key)
    counts = {status: 0 for status in ["PENDING", "RUNNING", "PASS", "FAIL", "BLOCKED", "SKIPPED"]}
    for gate in gates:
        counts[gate.status] = counts.get(gate.status, 0) + 1
    required_passed = sum(
        gate.status == "PASS" for gate in gates if gate.gate_key in PILOT_GATES
    )
    return {
        "pilot": pilot_view(row),
        "gates": [gate_view(gate) for gate in gates],
        "summary": {
            "required": len(PILOT_GATES),
            "passed": required_passed,
            "completion_percent": round(required_passed / len(PILOT_GATES) * 100, 1),
            "counts": counts,
            "ready_for_acceptance": row.status == "AWAITING_ACCEPTANCE",
            "accepted": row.status == "ACCEPTED",
        },
    }
