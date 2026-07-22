from __future__ import annotations

import agent_room_app  # noqa: F401 — install Agent Room APIs and governed workspace actions
from main import app
from release_version import APP_VERSION

app.version = APP_VERSION
