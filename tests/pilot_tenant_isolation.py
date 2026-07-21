#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pilot_api import ApiError, api, wait_ready


def mission(base_url: str, token: str, tenant: str, suffix: str) -> str:
    _, body, _ = api(
        base_url,
        "POST",
        "/api/missions",
        token=token,
        tenant=tenant,
        payload={
            "title": f"Pilot Tenant isolation {suffix}",
            "objective": f"Create durable evidence for Tenant isolation verification {suffix}.",
            "priority": "NORMAL",
        },
    )
    return body["key"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real BeezaOffice Tenant isolation Pilot gate.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--primary-tenant", required=True)
    parser.add_argument("--secondary-slug", default="pilot-isolation")
    parser.add_argument("--secondary-license-token-file", required=True)
    parser.add_argument("--pilot-key", required=True)
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--output", default="pilot-tenant-isolation-report.json")
    args = parser.parse_args()

    wait_ready(args.base_url)
    secondary_tenant = f"tenant:{args.secondary_slug}"
    try:
        api(
            args.base_url,
            "POST",
            "/api/enterprise/tenants",
            token=args.token,
            tenant=args.primary_tenant,
            payload={
                "slug": args.secondary_slug,
                "display_name": "Pilot Isolation Tenant",
                "data_region": "pilot-isolation",
                "isolation_mode": "ROW",
                "max_agents": 10,
                "max_concurrent_tasks": 5,
                "requests_per_minute": 6000,
                "air_gapped": False,
            },
        )
    except ApiError as exc:
        if exc.status != 409:
            raise

    secondary_license = Path(args.secondary_license_token_file).read_text(encoding="utf-8").strip()
    api(
        args.base_url,
        "POST",
        "/api/commercial/license/import",
        token=args.token,
        tenant=secondary_tenant,
        payload={"token": secondary_license},
    )

    mission_a = mission(args.base_url, args.token, args.primary_tenant, "PRIMARY")
    mission_b = mission(args.base_url, args.token, secondary_tenant, "SECONDARY")

    _, rows_a, headers_a = api(
        args.base_url,
        "GET",
        "/api/missions",
        token=args.token,
        tenant=args.primary_tenant,
    )
    _, rows_b, headers_b = api(
        args.base_url,
        "GET",
        "/api/missions",
        token=args.token,
        tenant=secondary_tenant,
    )
    keys_a = {row["key"] for row in rows_a}
    keys_b = {row["key"] for row in rows_b}
    checks = {
        "primary_contains_own": mission_a in keys_a,
        "primary_excludes_secondary": mission_b not in keys_a,
        "secondary_contains_own": mission_b in keys_b,
        "secondary_excludes_primary": mission_a not in keys_b,
        "primary_header": headers_a.get("x-beeza-tenant") == args.primary_tenant,
        "secondary_header": headers_b.get("x-beeza-tenant") == secondary_tenant,
    }
    for tenant, foreign in [
        (args.primary_tenant, mission_b),
        (secondary_tenant, mission_a),
    ]:
        try:
            api(
                args.base_url,
                "GET",
                f"/api/missions/{foreign}",
                token=args.token,
                tenant=tenant,
            )
        except ApiError as exc:
            checks[f"cross_read_denied_{tenant}"] = exc.status == 404
        else:
            checks[f"cross_read_denied_{tenant}"] = False

    passed = all(checks.values())
    completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {
        "gate": "tenant_isolation",
        "gate_status": "PASS" if passed else "FAIL",
        "primary_tenant": args.primary_tenant,
        "secondary_tenant": secondary_tenant,
        "mission_a": mission_a,
        "mission_b": mission_b,
        "checks": checks,
        "completed_at": completed_at,
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    api(
        args.base_url,
        "POST",
        f"/api/pilot/programs/{args.pilot_key}/gates",
        token=args.token,
        tenant=args.primary_tenant,
        payload={
            "gate_key": "tenant_isolation",
            "status": report["gate_status"],
            "source": "REAL_PILOT_ISOLATION",
            "summary": "Two licensed Pilot Tenants remained isolated" if passed else "Tenant isolation checks failed",
            "metrics": report,
            "artifact_ref": args.artifact_ref or str(output),
            "completed_at": completed_at,
        },
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit("Tenant isolation gate failed")


if __name__ == "__main__":
    main()
