from __future__ import annotations

from enterprise_models import EnterpriseTenant

# Phase 14 onboarding originally consumed the Governance Tenant `name` field,
# while EnterpriseTenant exposes `display_name`. Keep the compatibility alias at
# the model boundary so existing commercial seed code and imported extensions
# read the correct customer-facing organization name.
if not hasattr(EnterpriseTenant, "name"):
    EnterpriseTenant.name = property(  # type: ignore[attr-defined]
        lambda row: row.display_name,
        lambda row, value: setattr(row, "display_name", value),
    )
