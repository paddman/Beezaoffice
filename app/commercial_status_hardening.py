from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import commercial_service
import phase14_app
from commercial_models import DeploymentActivation, ReleaseManifest

_original_commercial_status = commercial_service.commercial_status


def hardened_commercial_status(db: Session, tenant_key: str):
    result = _original_commercial_status(db, tenant_key)
    release = db.scalar(
        select(ReleaseManifest)
        .where(
            ReleaseManifest.channel == "stable",
            ReleaseManifest.status == "PUBLISHED",
        )
        .order_by(ReleaseManifest.published_at.desc())
    )
    deployments = list(
        db.scalars(
            select(DeploymentActivation).where(
                DeploymentActivation.tenant_key == tenant_key,
                DeploymentActivation.status == "ACTIVE",
            )
        ).all()
    )
    signed_release = bool(
        release
        and release.image_digest.startswith("sha256:")
        and release.signature_ref
        and release.sbom_ref
        and release.provenance_ref
    )
    digest_matched = bool(
        signed_release
        and any(
            deployment.image_digest == release.image_digest
            for deployment in deployments
        )
    )
    result["release"] = (
        commercial_service.release_view(release)
        if release
        else result.get("release")
    )
    result["signed_release"] = signed_release
    result["deployment_digest_matched"] = digest_matched
    result["production_ready"] = bool(
        result.get("production_ready")
        and commercial_service.LICENSE_MODE == "enforce"
        and signed_release
        and digest_matched
    )
    result["readiness_requirements"] = {
        "license_enforced": commercial_service.LICENSE_MODE == "enforce",
        "onboarding_completed": bool(
            result.get("onboarding")
            and result["onboarding"].get("status") == "COMPLETED"
        ),
        "active_license": bool(result.get("license", {}).get("valid")),
        "active_deployment": bool(deployments),
        "signed_release": signed_release,
        "deployment_digest_matched": digest_matched,
    }
    return result


commercial_service.commercial_status = hardened_commercial_status
phase14_app.commercial_status = hardened_commercial_status
