from __future__ import annotations

import os

APP_VERSION = os.getenv("BEEZA_APP_VERSION", "0.16.1").strip() or "0.16.1"
RELEASE_CHANNEL = os.getenv("BEEZA_RELEASE_CHANNEL", "pilot").strip() or "pilot"
RELEASE_NAME = "Agent Rooms Release"
RELEASE_TAG = f"v{APP_VERSION}"
DEFAULT_RELEASE_IMAGE = f"ghcr.io/paddman/beezaoffice:{APP_VERSION}"
