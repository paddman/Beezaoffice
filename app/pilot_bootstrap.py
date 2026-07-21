from __future__ import annotations

import pilot_app  # noqa: F401 — install commercial runtime and pilot operations APIs
from main import app
from release_version import APP_VERSION

app.version = APP_VERSION
