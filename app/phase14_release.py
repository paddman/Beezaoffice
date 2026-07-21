from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
import phase14_app
from commercial_models import ReleaseManifest, release_view
from governance_models import GovernanceRole
from main import app, db_session, utcnow
from phase6_app import require_governance


class ReleasePublish(BaseModel):
    version: str = Field(min_length=3, max_length=40)
    channel: str = Field(default="stable", pattern="^(stable|candidate|preview|lts)$")
    image_ref: str = Field(min_length=8, max_length=500)
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature_ref: str = Field(min_length=8, max_length=1000)
    sbom_ref: str = Field(min_length=3, max_length=1000)
    provenance_ref: str = Field(min_length=3, max_length=1000)
    minimum_plan: str = Field(default="plan:team", min_length=3, max_length=100)
    notes: str = Field(default="", max_length=10000)
    source_commit: str = Field(default="", max_length=64)
    certificate_identity: str = Field(default="", max_length=1000)
    certificate_oidc_issuer: str = Field(default="", max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


rule = (
    "POST",
    re.compile(r"^/api/commercial/releases/publish$"),
    "commercial:release:publish",
)
if not any(
    existing[0] == rule[0]
    and existing[2] == rule[2]
    and existing[1].pattern == rule[1].pattern
    for existing in governance_service.ROUTE_RULES
):
    governance_service.ROUTE_RULES.insert(0, rule)
governance_service.EXECUTION_ACTIONS.add("commercial:release:publish")


@app.on_event("startup")
def add_release_permissions() -> None:
    with phase14_app.SessionLocal() as db:
        additions = {
            "role:executive": {"commercial:release:publish"},
            "role:service": {"commercial:release:publish"},
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


@app.post("/api/commercial/releases/publish", status_code=201)
def publish_release_manifest(
    payload: ReleasePublish,
    actor: str = Depends(require_governance("commercial:release:publish")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if "@sha256:" not in f"{payload.image_ref}@{payload.image_digest}":
        raise HTTPException(status_code=422, detail="Release image must be digest-pinned")
    now = utcnow()
    row = db.scalar(
        select(ReleaseManifest).where(
            ReleaseManifest.version == payload.version,
            ReleaseManifest.channel == payload.channel,
        )
    )
    values = {
        "status": "PUBLISHED",
        "image_ref": payload.image_ref,
        "image_digest": payload.image_digest,
        "signature_ref": payload.signature_ref,
        "sbom_ref": payload.sbom_ref,
        "provenance_ref": payload.provenance_ref,
        "minimum_plan": payload.minimum_plan,
        "notes": payload.notes,
        "metadata_json": {
            **payload.metadata,
            "source_commit": payload.source_commit,
            "certificate_identity": payload.certificate_identity,
            "certificate_oidc_issuer": payload.certificate_oidc_issuer,
            "published_by": actor,
        },
        "published_at": now,
    }
    if row is None:
        row = ReleaseManifest(
            release_key=f"REL-{uuid4().hex[:14].upper()}",
            version=payload.version,
            channel=payload.channel,
            created_at=now,
            **values,
        )
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return release_view(row)


phase14_app.ReleasePublish = ReleasePublish
phase14_app.publish_release_manifest = publish_release_manifest
