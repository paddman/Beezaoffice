from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class ApiError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def api(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str,
    tenant: str,
    identity: str = "human:owner",
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Beeza-Identity": identity,
            "X-Beeza-Tenant": tenant,
            "X-Beeza-Risk-Level": "LOW",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            body = json.loads(raw) if raw else None
            headers = {key.casefold(): value for key, value in response.headers.items()}
            return response.status, body, headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        raise ApiError(exc.code, body) from exc


def public_request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, bytes, dict[str, str]]:
    merged = dict(headers or {})
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=payload,
        headers=merged,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read(),
                {key.casefold(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            {key.casefold(): value for key, value in exc.headers.items()},
        )


def wait_ready(base_url: str, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, raw, _ = public_request(base_url, "GET", "/health/ready")
            if status == 200:
                body = json.loads(raw.decode())
                if body.get("status") == "ready":
                    return body
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"BeezaOffice did not become ready: {last_error}")
