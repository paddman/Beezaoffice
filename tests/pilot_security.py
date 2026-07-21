#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from pilot_api import api, public_request, wait_ready


def check(name: str, fn: Callable[[], tuple[bool, str]]) -> dict[str, Any]:
    try:
        passed, detail = fn()
    except Exception as exc:
        passed, detail = False, f"{type(exc).__name__}: {exc}"
    return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BeezaOffice pilot security review gate.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", default="pilot-token")
    parser.add_argument("--tenant", default="tenant:beeza")
    parser.add_argument("--minimum-score", type=int, default=90)
    parser.add_argument("--output", default="pilot-security-report.json")
    args = parser.parse_args()

    wait_ready(args.base_url)
    checks: list[dict[str, Any]] = []

    def unauthenticated_denied() -> tuple[bool, str]:
        status, _, _ = public_request(args.base_url, "GET", "/api/pilot/status")
        return status in {401, 403}, f"HTTP {status}"

    def invalid_token_denied() -> tuple[bool, str]:
        status, _, _ = public_request(
            args.base_url,
            "GET",
            "/api/pilot/status",
            token="invalid-pilot-token",
            headers={"X-Beeza-Tenant": args.tenant, "X-Beeza-Identity": "human:owner"},
        )
        return status in {401, 403}, f"HTTP {status}"

    def security_headers() -> tuple[bool, str]:
        _, _, headers = api(
            args.base_url,
            "GET",
            "/api/pilot/status",
            token=args.token,
            tenant=args.tenant,
        )
        required = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "content-security-policy": "default-src",
            "permissions-policy": "camera=()",
            "cache-control": "no-store",
        }
        missing = [
            key for key, value in required.items() if value not in headers.get(key, "")
        ]
        return not missing, "missing=" + ",".join(missing) if missing else "all required headers present"

    def server_header_removed() -> tuple[bool, str]:
        _, _, headers = api(
            args.base_url,
            "GET",
            "/api/pilot/status",
            token=args.token,
            tenant=args.tenant,
        )
        return "server" not in headers, f"server={headers.get('server')}"

    def oversized_body_rejected() -> tuple[bool, str]:
        status, _, _ = public_request(
            args.base_url,
            "POST",
            "/api/missions",
            token=args.token,
            payload=b"{}",
            headers={
                "X-Beeza-Identity": "human:owner",
                "X-Beeza-Tenant": args.tenant,
                "Content-Type": "application/json",
                "Content-Length": "999999999",
            },
        )
        return status == 413, f"HTTP {status}"

    def tenant_header_preserved() -> tuple[bool, str]:
        _, _, headers = api(
            args.base_url,
            "GET",
            "/api/missions",
            token=args.token,
            tenant=args.tenant,
        )
        return headers.get("x-beeza-tenant") == args.tenant, headers.get("x-beeza-tenant", "missing")

    def license_context_present() -> tuple[bool, str]:
        _, _, headers = api(
            args.base_url,
            "GET",
            "/api/commercial/status",
            token=args.token,
            tenant=args.tenant,
        )
        # Commercial recovery endpoints bypass execution enforcement, so inspect
        # the authenticated status payload instead of requiring a license header.
        _, body, _ = api(
            args.base_url,
            "GET",
            "/api/commercial/status",
            token=args.token,
            tenant=args.tenant,
        )
        mode = (body.get("license") or {}).get("mode")
        return mode in {"development", "warn", "enforce"}, f"license_mode={mode}"

    for name, fn in [
        ("unauthenticated protected API denied", unauthenticated_denied),
        ("invalid token denied", invalid_token_denied),
        ("security headers present", security_headers),
        ("server header removed", server_header_removed),
        ("oversized request rejected", oversized_body_rejected),
        ("tenant context preserved", tenant_header_preserved),
        ("license context present", license_context_present),
    ]:
        checks.append(check(name, fn))

    passed = sum(item["status"] == "PASS" for item in checks)
    score = round(passed / len(checks) * 100)
    report = {
        "gate": "security_review",
        "gate_status": "PASS" if score >= args.minimum_score else "FAIL",
        "score": score,
        "minimum_score": args.minimum_score,
        "checks": checks,
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if score < args.minimum_score:
        raise SystemExit(f"Security review failed with score {score}")


if __name__ == "__main__":
    main()
