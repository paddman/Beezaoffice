from __future__ import annotations

import os

APP_VERSION = os.getenv("BEEZA_APP_VERSION", "0.16.0").strip() or "0.16.0"
RELEASE_CHANNEL = os.getenv("BEEZA_RELEASE_CHANNEL", "pilot").strip() or "pilot"
RELEASE_NAME = "Pilot Operations Release"
RELEASE_TAG = f"v{APP_VERSION}"
DEFAULT_RELEASE_IMAGE = f"ghcr.io/paddman/beezaoffice:{APP_VERSION}"
