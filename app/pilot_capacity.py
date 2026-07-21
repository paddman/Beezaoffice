from __future__ import annotations

import os

from sqlalchemy import select

from enterprise_models import EnterpriseTenant
from enterprise_service import DEFAULT_TENANT
from main import SessionLocal, app, utcnow
from release_version import RELEASE_CHANNEL

PILOT_RATE_LIMIT_PER_MINUTE = max(
    600,
    int(os.getenv("BEEZA_PILOT_RATE_LIMIT_PER_MINUTE", "120000")),
)


@app.on_event("startup")
def provision_pilot_rate_capacity() -> None:
    with SessionLocal() as db:
        tenant = db.scalar(
            select(EnterpriseTenant).where(
                EnterpriseTenant.tenant_key == DEFAULT_TENANT,
                EnterpriseTenant.status == "ACTIVE",
            )
        )
        if tenant is None:
            return
        settings = dict(tenant.settings or {})
        if RELEASE_CHANNEL in {"pilot", "candidate"}:
            if "pilot_rate_limit_original" not in settings:
                settings["pilot_rate_limit_original"] = int(
                    settings.get("pilot_rate_limit_previous", tenant.requests_per_minute)
                )
            settings["pilot_rate_limit"] = PILOT_RATE_LIMIT_PER_MINUTE
            tenant.requests_per_minute = PILOT_RATE_LIMIT_PER_MINUTE
        else:
            original = settings.pop("pilot_rate_limit_original", None)
            settings.pop("pilot_rate_limit_previous", None)
            settings.pop("pilot_rate_limit", None)
            if original is not None:
                tenant.requests_per_minute = max(1, int(original))
        tenant.settings = settings
        tenant.updated_at = utcnow()
        db.commit()
