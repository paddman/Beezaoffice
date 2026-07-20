from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


class RuntimeAdapterError(RuntimeError):
    """Raised when a remote agent runtime cannot be reached or rejects work."""


@dataclass(slots=True)
class RuntimeConfig:
    key: str
    platform: str
    base_url: str
    auth_token: str = ""
    model: str = ""
    agent_target: str = ""
    workspace_dir: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/")


def _headers(config: RuntimeConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "BeezaOffice/0.3"}
    if config.auth_token:
        headers["Authorization"] = f"Bearer {config.auth_token}"
    return headers


async def _json_request(
    method: str,
    url: str,
    *,
    config: RuntimeConfig,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=8.0),
            follow_redirects=True,
        ) as client:
            response = await client.request(
                method,
                url,
                headers=_headers(config),
                json=payload,
            )
    except httpx.RequestError as exc:
        raise RuntimeAdapterError(
            f"{config.platform} connection failed: {exc}"
        ) from exc

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if response.status_code >= 400:
        try:
            detail: Any = response.json()
        except ValueError:
            detail = response.text[:500]
        raise RuntimeAdapterError(
            f"{config.platform} returned HTTP {response.status_code}: {detail}"
        )

    if not response.content:
        return {}, latency_ms
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeAdapterError(
            f"{config.platform} returned a non-JSON response"
        ) from exc
    if not isinstance(body, dict):
        body = {"data": body}
    return body, latency_ms


def _result_output(body: dict[str, Any]) -> Any:
    for key in ("output", "summary", "result", "final_response", "message"):
        value = body.get(key)
        if value not in (None, ""):
            return value
    return None


async def probe_runtime(config: RuntimeConfig) -> dict[str, Any]:
    if not config.configured:
        return {
            "status": "UNCONFIGURED",
            "latency_ms": None,
            "detail": "Set the runtime base URL and token in .env.",
        }

    platform = config.platform.lower()
    if platform == "openclaw":
        try:
            body, latency = await _json_request(
                "GET", f"{config.url}/healthz", config=config, timeout=10
            )
        except RuntimeAdapterError:
            body, latency = await _json_request(
                "GET", f"{config.url}/v1/models", config=config, timeout=10
            )
    elif platform in {"cherryagent", "hermes"}:
        body, latency = await _json_request(
            "GET", f"{config.url}/health", config=config, timeout=10
        )
    elif platform == "thclaws":
        body, latency = await _json_request(
            "GET", f"{config.url}/v1/models", config=config, timeout=10
        )
    else:
        body, latency = await _json_request(
            "GET", f"{config.url}/health", config=config, timeout=10
        )

    return {"status": "ONLINE", "latency_ms": latency, "detail": body}


def _mission_prompt(payload: dict[str, Any]) -> str:
    prompt = str(payload.get("prompt") or "").strip()
    if prompt:
        return prompt
    return (
        f"Mission {payload['mission_key']}: {payload['title']}\n\n"
        f"Objective: {payload['objective']}\n"
        f"Priority: {payload['priority']}\n\n"
        "Work as a BeezaOffice agent peer. Plan the work, execute only within your "
        "configured permissions, preserve evidence, report blockers, and return a "
        "concise result with verification."
    )


async def dispatch_runtime(config: RuntimeConfig, payload: dict[str, Any]) -> dict[str, Any]:
    if not config.configured:
        raise RuntimeAdapterError(
            f"{config.platform} is not configured. Set its base URL in .env."
        )

    prompt = _mission_prompt(payload)
    platform = config.platform.lower()

    if platform == "openclaw":
        model = config.agent_target or "openclaw/default"
        body, latency = await _json_request(
            "POST",
            f"{config.url}/v1/chat/completions",
            config=config,
            timeout=180,
            payload={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an agent runtime connected to BeezaOffice AI Workforce OS. "
                            "Treat the mission contract as authoritative, use tools according to "
                            "your policy, and return evidence-backed completion or a blocker."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "user": f"beeza:{payload['mission_key']}",
                "stream": False,
            },
        )
        choices = body.get("choices") or []
        output = ""
        if choices and isinstance(choices[0], dict):
            output = str((choices[0].get("message") or {}).get("content") or "")
        return {
            "remote_id": body.get("id"),
            "status": "COMPLETED",
            "latency_ms": latency,
            "output": output,
            "raw": body,
        }

    if platform == "cherryagent":
        roles = payload.get("roles") or []
        tags = list(dict.fromkeys([*(payload.get("tags") or []), "beezaoffice", payload["mission_key"]]))
        body, latency = await _json_request(
            "POST",
            f"{config.url}/orchestrator/runs",
            config=config,
            timeout=30,
            payload={"goal": prompt, "preferredRoles": roles, "tags": tags},
        )
        remote_id = body.get("runId") or body.get("run_id") or body.get("id")
        return {
            "remote_id": remote_id,
            "status": str(body.get("status") or "STARTED").upper(),
            "latency_ms": latency,
            "output": _result_output(body),
            "raw": body,
        }

    if platform == "hermes":
        instructions = str(
            payload.get("instructions")
            or (
                "You are a specialist in a BeezaOffice mission. Use your tools, "
                "preserve evidence, respect approvals, and clearly report completion or blockers."
            )
        )
        body, latency = await _json_request(
            "POST",
            f"{config.url}/v1/runs",
            config=config,
            timeout=30,
            payload={
                "input": prompt,
                "session_id": f"beeza-{payload['mission_key']}",
                "instructions": instructions,
            },
        )
        return {
            "remote_id": body.get("run_id") or body.get("id"),
            "status": str(body.get("status") or "STARTED").upper(),
            "latency_ms": latency,
            "output": _result_output(body),
            "raw": body,
        }

    if platform == "thclaws":
        request_body: dict[str, Any] = {
            "prompt": prompt,
            "system": (
                "You are a sovereign agent peer operating under BeezaOffice. "
                "Use workspace skills and tools, preserve evidence, and stop for "
                "approval before consequential actions."
            ),
            "stream": False,
        }
        if config.model:
            request_body["model"] = config.model
        if config.workspace_dir:
            request_body["workspace_dir"] = config.workspace_dir
        body, latency = await _json_request(
            "POST",
            f"{config.url}/agent/run",
            config=config,
            timeout=300,
            payload=request_body,
        )
        return {
            "remote_id": body.get("run_id") or body.get("session_id"),
            "status": "COMPLETED",
            "latency_ms": latency,
            "output": body.get("summary"),
            "raw": body,
        }

    raise RuntimeAdapterError(f"Unsupported runtime platform: {config.platform}")


async def get_runtime_status(config: RuntimeConfig, remote_id: str) -> dict[str, Any]:
    """Poll a long-running remote run using the runtime's public control API."""
    platform = config.platform.lower()
    if platform == "cherryagent":
        body, latency = await _json_request(
            "GET", f"{config.url}/orchestrator/runs/{remote_id}", config=config, timeout=30
        )
    elif platform == "hermes":
        body, latency = await _json_request(
            "GET", f"{config.url}/v1/runs/{remote_id}", config=config, timeout=30
        )
    else:
        raise RuntimeAdapterError(
            f"{config.platform} dispatches are synchronous in Phase 2 and cannot be polled."
        )

    return {
        "status": str(body.get("status") or "UNKNOWN"),
        "latency_ms": latency,
        "output": _result_output(body),
        "last_event": body.get("last_event") or body.get("event"),
        "raw": body,
    }


async def stop_runtime_run(config: RuntimeConfig, remote_id: str) -> dict[str, Any]:
    """Request a safe stop. Hermes exposes this in its stable Runs API."""
    if config.platform.lower() != "hermes":
        raise RuntimeAdapterError(
            f"Stop control is not available for {config.platform} in Phase 2."
        )
    body, latency = await _json_request(
        "POST",
        f"{config.url}/v1/runs/{remote_id}/stop",
        config=config,
        payload={},
        timeout=30,
    )
    return {"status": str(body.get("status") or "STOPPING"), "latency_ms": latency, "raw": body}


async def approve_runtime_run(
    config: RuntimeConfig,
    remote_id: str,
    choice: str,
) -> dict[str, Any]:
    """Resolve a Hermes tool approval without exposing its token to the browser."""
    if config.platform.lower() != "hermes":
        raise RuntimeAdapterError(
            f"Approval control is not available for {config.platform} in Phase 2."
        )
    body, latency = await _json_request(
        "POST",
        f"{config.url}/v1/runs/{remote_id}/approval",
        config=config,
        payload={"choice": choice},
        timeout=30,
    )
    return {"status": str(body.get("status") or "RUNNING"), "latency_ms": latency, "raw": body}
