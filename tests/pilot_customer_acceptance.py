#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pilot_api import ApiError, api, wait_ready


def find_or_create_pilot(
    base_url: str,
    token: str,
    tenant: str,
    customer_name: str,
    version: str,
    runtimes: list[str],
) -> dict[str, Any]:
    _, programs, _ = api(
        base_url,
        "GET",
        "/api/pilot/programs",
        token=token,
        tenant=tenant,
    )
    for item in programs:
        pilot = item.get("pilot") or {}
        if pilot.get("target_version") == version:
            return item
    _, created, _ = api(
        base_url,
        "POST",
        "/api/pilot/programs",
        token=token,
        tenant=tenant,
        payload={
            "customer_name": customer_name,
            "environment": "pilot",
            "target_version": version,
            "runtime_keys": runtimes,
            "acceptance_criteria": {
                "customer_signoff_required": True,
                "workflow": "first-customer-journey",
            },
            "notes": "Created by the 0.16.0 customer-acceptance runner.",
        },
    )
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BeezaOffice first-customer acceptance journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", default="pilot-token")
    parser.add_argument("--tenant", default="tenant:beeza")
    parser.add_argument("--customer-name", default="BeezaOffice Internal Pilot")
    parser.add_argument("--version", default="0.16.0")
    parser.add_argument("--runtimes", default="")
    parser.add_argument("--signoff-name", required=True)
    parser.add_argument("--signoff-note", required=True)
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--output", default="pilot-customer-acceptance-report.json")
    args = parser.parse_args()

    wait_ready(args.base_url)
    runtime_keys = [item.strip() for item in args.runtimes.split(",") if item.strip()]
    readiness = find_or_create_pilot(
        args.base_url,
        args.token,
        args.tenant,
        args.customer_name,
        args.version,
        runtime_keys,
    )
    pilot = readiness["pilot"]
    pilot_key = pilot["key"]

    checks: list[dict[str, Any]] = []

    _, commercial, _ = api(
        args.base_url,
        "GET",
        "/api/commercial/status",
        token=args.token,
        tenant=args.tenant,
    )
    checks.append(
        {
            "name": "commercial version",
            "status": "PASS" if commercial.get("version") == args.version else "FAIL",
            "detail": commercial.get("version"),
        }
    )

    try:
        _, brand, _ = api(
            args.base_url,
            "PUT",
            "/api/commercial/brand",
            token=args.token,
            tenant=args.tenant,
            payload={
                "product_name": f"{args.customer_name} AI Office",
                "company_name": args.customer_name,
                "settings": {"white_label": True, "pilot": True},
            },
        )
        checks.append({"name": "white-label profile", "status": "PASS", "detail": brand["product_name"]})
    except ApiError as exc:
        checks.append({"name": "white-label profile", "status": "FAIL", "detail": str(exc)})

    _, mission, _ = api(
        args.base_url,
        "POST",
        "/api/missions",
        token=args.token,
        tenant=args.tenant,
        payload={
            "title": "First customer pilot mission",
            "objective": (
                "Create a safe executive pilot brief proving mission creation, Tenant isolation, "
                "governance and durable retrieval without modifying external systems."
            ),
            "priority": "NORMAL",
        },
    )
    mission_key = mission["key"]
    _, mission_detail, _ = api(
        args.base_url,
        "GET",
        f"/api/missions/{mission_key}",
        token=args.token,
        tenant=args.tenant,
    )
    checks.append(
        {
            "name": "mission lifecycle",
            "status": "PASS" if mission_detail.get("key") == mission_key else "FAIL",
            "detail": mission_key,
        }
    )

    _, pilot_readiness, _ = api(
        args.base_url,
        "GET",
        f"/api/pilot/programs/{pilot_key}",
        token=args.token,
        tenant=args.tenant,
    )
    checks.append(
        {
            "name": "pilot evidence ledger",
            "status": "PASS" if len(pilot_readiness.get("gates") or []) == 10 else "FAIL",
            "detail": f"{len(pilot_readiness.get('gates') or [])} gates",
        }
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {
        "gate": "customer_acceptance",
        "gate_status": "PASS" if not failed else "FAIL",
        "pilot_key": pilot_key,
        "tenant_key": args.tenant,
        "customer_name": args.customer_name,
        "version": args.version,
        "mission_key": mission_key,
        "signoff": {
            "name": args.signoff_name,
            "note": args.signoff_note,
            "at": completed_at,
        },
        "checks": checks,
        "summary": (
            f"Customer journey accepted by {args.signoff_name}"
            if not failed
            else f"Customer journey failed {len(failed)} checks"
        ),
        "completed_at": completed_at,
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    api(
        args.base_url,
        "POST",
        f"/api/pilot/programs/{pilot_key}/gates",
        token=args.token,
        tenant=args.tenant,
        payload={
            "gate_key": "customer_acceptance",
            "status": report["gate_status"],
            "source": "CUSTOMER_SIGNOFF",
            "summary": report["summary"],
            "metrics": {
                "checks": len(checks),
                "passed": len(checks) - len(failed),
                "signoff_name": args.signoff_name,
                "mission_key": mission_key,
            },
            "artifact_ref": args.artifact_ref or str(output.resolve()),
            "completed_at": completed_at,
        },
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    if failed:
        raise SystemExit("Customer acceptance gate failed")


if __name__ == "__main__":
    main()
