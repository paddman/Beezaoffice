from __future__ import annotations

import re

import phase14_app

_RULES = [
    ("PATCH", re.compile(r"^/api/agent-rooms/[^/]+$"), "registry"),
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/(messages|tasks)$"), "collaboration"),
    ("POST", re.compile(r"^/api/agent-rooms/[^/]+/notes$"), "registry"),
    ("DELETE", re.compile(r"^/api/agent-rooms/[^/]+/notes/[^/]+$"), "registry"),
]

for rule in reversed(_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[1].pattern == rule[1].pattern
        and existing[2] == rule[2]
        for existing in phase14_app._FEATURE_ROUTES
    ):
        phase14_app._FEATURE_ROUTES.insert(0, rule)
