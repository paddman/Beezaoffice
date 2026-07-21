from __future__ import annotations

import phase14_app  # noqa: F401 — install Phase 1–14 productized runtime
import commercial_schema_hardening  # noqa: F401 — entitlement source constraint migration
import commercial_hardening  # noqa: F401 — contract/license intersection and quotas
import commercial_quota_hardening  # noqa: F401 — tenant quota and enterprise feature access
import phase14_release  # noqa: F401 — signed release manifest publishing
import phase14_observability  # noqa: F401 — commercial health and Prometheus metrics
from main import app

app.version = "0.15.0"
