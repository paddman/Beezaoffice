from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import commercial_service
import phase14_app
from commercial_models import DeploymentActivation, ReleaseManifest
from main import utcnow
from release_version import APP_VERSION, DEFAULT_RELEASE_IMAGE, RELEASE_CHANNEL, RELEASE_NAME

_original_seed = commercial_service.seed_commercial
_original_status = phase14_app.commercial_status

commercial_service.RELEASE_IMAGE = DEFAULT_RELEASE_IMAGE


def seed_release_version(db: Session) -> None:
    _original_seed(db)
    now = utcnow()
    deployment = db.scalar(
        select(DeploymentActivation).where(
            DeploymentActivation.deployment_id == commercial_service.DEPLOYMENT_ID
        )
    )
    if deployment is not None and deployment.version != APP_VERSION:
        deployment.version = APP_VERSION
        deployment.last_seen_at = now
    release = db.scalar(
        select(ReleaseManifest).where(
            ReleaseManifest.version == APP_VERSION,
            ReleaseManifest.channel == "stable",
        )
    )
    if release is None:
        release = ReleaseManifest(
            release_key=f"REL-{APP_VERSION}-STABLE",
            version=APP_VERSION,
            channel="stable",
            status="UNSIGNED",
            image_ref=DEFAULT_RELEASE_IMAGE,
            image_digest="",
            signature_ref="",
            sbom_ref="",
            provenance_ref="",
            minimum_plan="plan:team",
            notes=f"{RELEASE_NAME}. Signed release workflow promotes {RELEASE_CHANNEL} evidence after pilot acceptance.",
            metadata_json={
                "release": RELEASE_NAME,
                "channel": RELEASE_CHANNEL,
                "pilot_gated": True,
            },
            created_at=now,
            published_at=None,
        )
        db.add(release)
    db.commit()


def versioned_commercial_status(db: Session, tenant_key: str):
    result = _original_status(db, tenant_key)
    result["version"] = APP_VERSION
    result["release_channel"] = RELEASE_CHANNEL
    result["release_name"] = RELEASE_NAME
    return result


commercial_service.seed_commercial = seed_release_version
phase14_app.seed_commercial = seed_release_version
commercial_service.commercial_status = versioned_commercial_status
phase14_app.commercial_status = versioned_commercial_status
