from __future__ import annotations

import os
from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse

from main import app, engine, redis_client
from phase6_app import require_governance
from schema_service import schema_status

SCHEMA_STRICT = os.getenv("BEEZA_SCHEMA_STRICT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


remove_route("/health/ready", "GET")


@app.get("/health/ready")
def migration_aware_readiness() -> JSONResponse:
    database = True
    queue = True
    schema: dict[str, Any]
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        schema = schema_status(engine)
    except Exception as exc:
        database = False
        schema = {
            "managed": False,
            "current_revision": None,
            "expected_revision": None,
            "up_to_date": False,
            "error": str(exc)[:500],
        }
    try:
        redis_client.ping()
    except Exception:
        queue = False
    ready = database and queue and (schema.get("up_to_date") or not SCHEMA_STRICT)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "database": database,
            "queue": queue,
            "schema": schema,
            "schema_strict": SCHEMA_STRICT,
        },
    )


@app.get("/api/system/schema")
def read_schema_status(
    _: str = Depends(require_governance("api:read")),
) -> dict[str, Any]:
    return {**schema_status(engine), "strict": SCHEMA_STRICT}


@app.on_event("startup")
def enforce_schema_revision() -> None:
    if not SCHEMA_STRICT:
        return
    status = schema_status(engine)
    if not status["up_to_date"]:
        raise RuntimeError(
            "Database schema is not at the expected Alembic revision: "
            f"current={status['current_revision']} expected={status['expected_revision']}"
        )
