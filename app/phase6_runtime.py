from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from governance_models import GovernanceIdentity, RoleBinding
from main import SessionLocal, app, utcnow
from phase6_app import app as governed_app  # noqa: F401 — register Phase 6
import governance_hardening  # noqa: F401 — scoped RBAC and recovery middleware

app.version = "0.7.0"


@app.on_event("startup")
def seed_secondary_approver() -> None:
    """Keep requester and approver identities separate in the default deployment."""
    with SessionLocal() as db:
        now = utcnow()
        identity_key = "human:executive"
        identity = db.scalar(
            select(GovernanceIdentity).where(
                GovernanceIdentity.identity_key == identity_key
            )
        )
        if identity is None:
            db.add(
                GovernanceIdentity(
                    identity_key=identity_key,
                    tenant_key="tenant:beeza",
                    identity_type="HUMAN",
                    display_name="Beeza Executive Approver",
                    department_key="dept:executive",
                    status="ACTIVE",
                    clearance="RESTRICTED",
                    daily_budget_usd=1000.0,
                    monthly_budget_usd=30000.0,
                    attributes={"seeded": True, "purpose": "secondary approval"},
                    created_at=now,
                    updated_at=now,
                )
            )
        binding = db.scalar(
            select(RoleBinding).where(
                RoleBinding.identity_key == identity_key,
                RoleBinding.role_key == "role:executive",
                RoleBinding.scope_type == "GLOBAL",
            )
        )
        if binding is None:
            db.add(
                RoleBinding(
                    binding_key=f"BIND-{uuid4().hex[:14].upper()}",
                    identity_key=identity_key,
                    role_key="role:executive",
                    scope_type="GLOBAL",
                    scope_key="*",
                    created_by="system:bootstrap",
                    created_at=now,
                )
            )
        db.commit()
