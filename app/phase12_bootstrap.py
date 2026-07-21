from __future__ import annotations

import importlib

import phase12_runtime
import phase11_app
import phase11_hardening
import protocol_service
from main import app

# Phase 11 hardening keeps its original protocol constructor in a module global.
# Phase 12 wraps the hardened constructor to add tenant scopes. Reload the base
# service once, restore the Phase 11 inner reference, then expose the Phase 12
# outer wrapper. This preserves validation and avoids a recursive wrapper chain.
_base_protocol_service = importlib.reload(protocol_service)
phase11_hardening._original_create_protocol_task = _base_protocol_service.create_protocol_task
_base_protocol_service.create_protocol_task = phase12_runtime.enterprise_create_protocol_task
phase11_app.create_protocol_task = phase12_runtime.enterprise_create_protocol_task

import phase12_hardening  # noqa: E402,F401 — activate OIDC, API-key and tenant ownership checks

app.version = "0.13.0"
