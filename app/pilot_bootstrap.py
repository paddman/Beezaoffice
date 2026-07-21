from __future__ import annotations

import pilot_app  # noqa: F401 — install commercial runtime and pilot operations APIs
import pilot_version_hardening  # noqa: F401 — propagate 0.16.0 status and release manifests
import pilot_security_hardening  # noqa: F401 — HTTP security baseline and body limits
import pilot_capacity  # noqa: F401 — Pilot-only authenticated API capacity profile
from main import app
from release_version import APP_VERSION

app.version = APP_VERSION
