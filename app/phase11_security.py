from __future__ import annotations

import os
from typing import Callable
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

import phase11_runtime  # noqa: F401 — install governed Phase 11 runtime
from main import app
from phase11_app import MCP_PROTOCOL_VERSION
from protocol_service import PROTOCOL_PUBLIC_URL


def origin_of(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


_configured = {
    item.strip().rstrip("/")
    for item in os.getenv("BEEZA_MCP_ALLOWED_ORIGINS", "").split(",")
    if item.strip()
}
_public_origin = origin_of(PROTOCOL_PUBLIC_URL)
if _public_origin:
    _configured.add(_public_origin)
_configured.update({"http://localhost:8080", "http://127.0.0.1:8080"})
MCP_ALLOWED_ORIGINS = frozenset(_configured)


@app.middleware("http")
async def mcp_transport_security(request: Request, call_next: Callable):
    if request.url.path != "/mcp":
        return await call_next(request)

    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") not in MCP_ALLOWED_ORIGINS:
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "MCP Origin is not allowed"},
            },
        )

    version = request.headers.get("MCP-Protocol-Version")
    if version and version != MCP_PROTOCOL_VERSION:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": f"Unsupported MCP protocol version {version}",
                    "data": {"supported": MCP_PROTOCOL_VERSION},
                },
            },
        )
    return await call_next(request)
