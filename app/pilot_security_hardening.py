from __future__ import annotations

import os
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from main import app

MAX_REQUEST_BYTES = int(os.getenv("BEEZA_MAX_REQUEST_BYTES", "2097152"))
FORCE_HTTPS = os.getenv("BEEZA_FORCE_HTTPS", "false").strip().lower() == "true"


@app.middleware("http")
async def pilot_security_headers(request: Request, call_next: Callable):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Request body exceeds the configured limit",
                        "maximum_bytes": MAX_REQUEST_BYTES,
                    },
                )
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})

    if FORCE_HTTPS and request.url.scheme != "https":
        forwarded = request.headers.get("x-forwarded-proto", "").lower()
        if forwarded != "https" and request.url.path not in {"/health/live", "/health/ready"}:
            return JSONResponse(status_code=426, content={"detail": "HTTPS is required"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if FORCE_HTTPS or request.headers.get("x-forwarded-proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if "server" in response.headers:
        del response.headers["server"]
    return response
