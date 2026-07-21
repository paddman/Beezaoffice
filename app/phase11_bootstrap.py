from __future__ import annotations

import phase11_runtime  # noqa: F401 — install hardened Phase 11 runtime
from main import app

app.version = "0.12.0"

# Starlette evaluates routes in declaration order. The generic GET /tasks/{task_id}
# route would otherwise consume /tasks/{task_id}:subscribe as a task ID. Keep the
# A2A suffix operations ahead of the generic task lookup.
_specific_paths = {
    "/tasks/{task_id}:subscribe",
    "/tasks/{task_id}:cancel",
}
_specific = [
    route for route in app.router.routes
    if getattr(route, "path", None) in _specific_paths
]
_remaining = [
    route for route in app.router.routes
    if getattr(route, "path", None) not in _specific_paths
]
_generic_index = next(
    (
        index
        for index, route in enumerate(_remaining)
        if getattr(route, "path", None) == "/tasks/{task_id}"
    ),
    len(_remaining),
)
app.router.routes = [
    *_remaining[:_generic_index],
    *_specific,
    *_remaining[_generic_index:],
]
