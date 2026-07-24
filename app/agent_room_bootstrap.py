from __future__ import annotations

import agent_room_app  # noqa: F401 — install Agent Room APIs and governed workspace actions
import agent_room_tenant_hardening  # noqa: F401 — include every default-Tenant registered Agent
import agent_room_presence  # noqa: F401 — reconcile Room state with live Agent workload
import agent_room_commercial  # noqa: F401 — enforce Registry and Collaboration entitlements
import company_bootstrap  # noqa: F401 — create the governed Beeza AI Company organization
import paddman_portfolio_app  # noqa: F401 — connect every paddman GitHub repository to the company portfolio
from main import app
from release_version import APP_VERSION

app.version = APP_VERSION
