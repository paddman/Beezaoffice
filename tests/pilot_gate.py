#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_TENANT = "tenant:beeza"
SECOND_TENANT = "tenant:pilot-b"
APP_VERSION = "0.16.1"
SCHEMA_REVISION = "20260722_0003"


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
    tenant: str = DEFAULT_TENANT,
    payload: dict[str, Any] | None = None,
    token: str = "pilot-token",
) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Beeza-Identity": "human:owner",
            "X-Beeza-Tenant": tenant,
            "X-Beeza-Risk-Level": "LOW",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
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


def public_get(base_url: str, path: str) -> tuple[int, Any]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}")
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read().decode()
        return response.status, json.loads(raw) if raw else None


def wait_ready(base_url: str, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, body = public_get(base_url, "/health/ready")
            if status == 200 and body.get("status") == "ready":
                return body
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"BeezaOffice did not become ready: {last_error}")


def ensure_second_tenant(base_url: str, secondary_license_token: str | None) -> None:
    try:
        api(
            base_url,
            "POST",
            "/api/enterprise/tenants",
            payload={
                "slug": "pilot-b",
                "display_name": "Pilot Tenant B",
                "data_region": "test-region-b",
                "isolation_mode": "ROW",
                "max_agents": 20,
                "max_concurrent_tasks": 10,
                "requests_per_minute": 600,
                "air_gapped": False,
            },
        )
    except ApiError as exc:
        if exc.status != 409:
            raise
    if secondary_license_token:
        _, imported, _ = api(
            base_url,
            "POST",
            "/api/commercial/license/import",
            tenant=SECOND_TENANT,
            payload={"token": secondary_license_token},
        )
        assert imported.get("tenant_key") == SECOND_TENANT, imported
        assert imported.get("status") == "ACTIVE", imported


def create_mission(base_url: str, tenant: str, suffix: str) -> str:
    _, body, _ = api(
        base_url,
        "POST",
        "/api/missions",
        tenant=tenant,
        payload={
            "title": f"Pilot isolation mission {suffix}",
            "objective": f"Verify durable Tenant isolation and restore path for {suffix}.",
            "priority": "NORMAL",
        },
    )
    key = body.get("key")
    if not key:
        raise AssertionError(f"Mission creation returned no key: {body}")
    return key


def assert_tenant_isolation(base_url: str, mission_a: str, mission_b: str) -> None:
    _, missions_a, headers_a = api(base_url, "GET", "/api/missions")
    _, missions_b, headers_b = api(
        base_url, "GET", "/api/missions", tenant=SECOND_TENANT
    )
    keys_a = {row["key"] for row in missions_a}
    keys_b = {row["key"] for row in missions_b}
    assert mission_a in keys_a and mission_b not in keys_a, (mission_a, mission_b, keys_a)
    assert mission_b in keys_b and mission_a not in keys_b, (mission_a, mission_b, keys_b)
    assert headers_a.get("x-beeza-tenant") == DEFAULT_TENANT, headers_a
    assert headers_b.get("x-beeza-tenant") == SECOND_TENANT, headers_b
    for tenant, foreign_key in [
        (DEFAULT_TENANT, mission_b),
        (SECOND_TENANT, mission_a),
    ]:
        try:
            api(base_url, "GET", f"/api/missions/{foreign_key}", tenant=tenant)
        except ApiError as exc:
            assert exc.status == 404, exc
        else:
            raise AssertionError(f"{tenant} read foreign Mission {foreign_key}")


def assert_agent_rooms(base_url: str) -> dict[str, Any]:
    _, status, _ = api(base_url, "GET", "/api/agent-rooms/status")
    assert status.get("version") == APP_VERSION, status
    assert status.get("rooms", 0) >= 12, status
    _, rooms, _ = api(base_url, "GET", "/api/agent-rooms")
    assert len(rooms) >= 12, rooms
    first = rooms[0]
    agent_key = first["room"]["agent_key"]
    _, detail, _ = api(base_url, "GET", f"/api/agent-rooms/{agent_key}")
    assert detail["room"]["agent_key"] == agent_key, detail
    assert detail["room"]["background_asset"].startswith("/static/"), detail
    assert detail["asset_guide"]["background"].endswith("background.webp"), detail
    return status


def assert_schema(base_url: str) -> dict[str, Any]:
    ready = wait_ready(base_url)
    schema = ready.get("schema") or {}
    assert ready.get("schema_strict") is True, ready
    assert schema.get("managed") is True, schema
    assert schema.get("up_to_date") is True, schema
    assert schema.get("current_revision") == schema.get("expected_revision"), schema
    assert schema.get("expected_revision") == SCHEMA_REVISION, schema
    _, status, _ = api(base_url, "GET", "/api/system/schema")
    assert status.get("up_to_date") is True, status
    return status


def assert_release_and_pilot(base_url: str, expected_license_mode: str) -> dict[str, Any]:
    _, commercial, _ = api(base_url, "GET", "/api/commercial/status")
    assert commercial.get("version") == APP_VERSION, commercial
    assert commercial.get("license", {}).get("mode") == expected_license_mode, commercial
    if expected_license_mode == "enforce":
        assert commercial.get("license", {}).get("valid") is True, commercial
    _, pilot, _ = api(base_url, "GET", "/api/pilot/status")
    assert pilot.get("version") == APP_VERSION, pilot
    assert pilot.get("release", {}).get("tag") == f"v{APP_VERSION}", pilot
    current = pilot.get("current") or {}
    assert len(current.get("gates") or []) == 10, current
    return pilot


def prepare(
    base_url: str,
    state_path: Path,
    expected_license_mode: str,
    secondary_license_token: str | None,
) -> None:
    schema = assert_schema(base_url)
    ensure_second_tenant(base_url, secondary_license_token)
    mission_a = create_mission(base_url, DEFAULT_TENANT, "A")
    mission_b = create_mission(base_url, SECOND_TENANT, "B")
    assert_tenant_isolation(base_url, mission_a, mission_b)
    agent_rooms = assert_agent_rooms(base_url)
    pilot = assert_release_and_pilot(base_url, expected_license_mode)
    state = {
        "mission_a": mission_a,
        "mission_b": mission_b,
        "schema_revision": schema["current_revision"],
        "pilot_key": (pilot.get("current") or {}).get("pilot", {}).get("key"),
        "version": APP_VERSION,
        "license_mode": expected_license_mode,
        "agent_rooms": agent_rooms.get("rooms", 0),
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "prepare", "status": "passed", **state}, indent=2))


def verify(base_url: str, state_path: Path, expected_license_mode: str) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    schema = assert_schema(base_url)
    assert schema["current_revision"] == state["schema_revision"]
    assert state["version"] == APP_VERSION
    assert_tenant_isolation(base_url, state["mission_a"], state["mission_b"])
    _, mission_a, _ = api(base_url, "GET", f"/api/missions/{state['mission_a']}")
    _, mission_b, _ = api(
        base_url,
        "GET",
        f"/api/missions/{state['mission_b']}",
        tenant=SECOND_TENANT,
    )
    assert mission_a["key"] == state["mission_a"]
    assert mission_b["key"] == state["mission_b"]
    assert assert_agent_rooms(base_url).get("rooms", 0) >= state.get("agent_rooms", 0)
    pilot = assert_release_and_pilot(base_url, expected_license_mode)
    assert (pilot.get("current") or {}).get("pilot", {}).get("key") == state["pilot_key"]
    print(json.dumps({"gate": "restore-verify", "status": "passed", **state}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--state", default="pilot-state.json")
    parser.add_argument("--mode", choices=["prepare", "verify"], default="prepare")
    parser.add_argument(
        "--expected-license-mode",
        choices=["development", "warn", "enforce"],
        default="development",
    )
    parser.add_argument("--secondary-license-token-file", default="")
    args = parser.parse_args()
    state_path = Path(args.state).resolve()
    secondary_token = None
    if args.secondary_license_token_file:
        secondary_token = Path(args.secondary_license_token_file).read_text(encoding="utf-8").strip()
    if args.expected_license_mode == "enforce" and args.mode == "prepare" and not secondary_token:
        raise SystemExit("--secondary-license-token-file is required for enforce-mode Tenant isolation")
    if args.mode == "prepare":
        prepare(args.base_url, state_path, args.expected_license_mode, secondary_token)
    else:
        verify(args.base_url, state_path, args.expected_license_mode)


if __name__ == "__main__":
    main()
