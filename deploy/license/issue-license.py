#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt

PLAN_FEATURES = {
    "plan:team": [
        "core.missions", "collaboration", "meetings", "governance", "registry",
        "scheduler", "evaluation", "sop", "protocol", "runtime.dispatch",
        "business", "metrics",
    ],
    "plan:enterprise": [
        "core.missions", "collaboration", "meetings", "governance", "registry",
        "scheduler", "evaluation", "sop", "protocol", "runtime.dispatch",
        "enterprise", "business", "marketplace", "white_label", "backup_dr",
        "siem", "metrics", "kubernetes",
    ],
    "plan:sovereign": [
        "core.missions", "collaboration", "meetings", "governance", "registry",
        "scheduler", "evaluation", "sop", "protocol", "runtime.dispatch",
        "enterprise", "business", "marketplace", "white_label", "backup_dr",
        "siem", "metrics", "kubernetes",
    ],
}

PLAN_LIMITS = {
    "plan:team": {
        "max_agents": 50,
        "max_concurrent_tasks": 20,
        "max_tenants": 1,
        "max_deployments": 1,
    },
    "plan:enterprise": {
        "max_agents": 500,
        "max_concurrent_tasks": 100,
        "max_tenants": 10,
        "max_deployments": 4,
    },
    "plan:sovereign": {
        "max_agents": 1000,
        "max_concurrent_tasks": 200,
        "max_tenants": 50,
        "max_deployments": 20,
    },
}


def parse_list(value: str | None, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def parse_limits(value: str | None, fallback: dict[str, int]) -> dict[str, int]:
    if value is None:
        return fallback
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise SystemExit("--limits must be a JSON object")
    return {str(key): int(item) for key, item in parsed.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue a deployment-bound BeezaOffice commercial license JWT."
    )
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--tenant-key", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--plan-key",
        choices=sorted(PLAN_FEATURES),
        default="plan:enterprise",
    )
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--not-before-minutes", type=int, default=0)
    parser.add_argument("--issuer", default="beezaoffice-license")
    parser.add_argument("--audience", default="beezaoffice")
    parser.add_argument("--subject")
    parser.add_argument("--license-key")
    parser.add_argument("--features", help="Comma-separated feature override")
    parser.add_argument("--limits", help="JSON object override")
    parser.add_argument("--customer-name", default="")
    parser.add_argument("--contract-reference", default="")
    parser.add_argument("--output", default="beeza-license.jwt")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.days < 1 or args.days > 3650:
        raise SystemExit("--days must be between 1 and 3650")
    private_path = Path(args.private_key).resolve()
    output_path = Path(args.output).resolve()
    if output_path.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite {output_path}; use --force")

    private_key = private_path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc)
    not_before = now + timedelta(minutes=args.not_before_minutes)
    expires = not_before + timedelta(days=args.days)
    plan_features = PLAN_FEATURES[args.plan_key]
    plan_limits = PLAN_LIMITS[args.plan_key]
    license_key = args.license_key or f"LIC-{uuid4().hex[:20].upper()}"

    claims = {
        "iss": args.issuer,
        "aud": args.audience,
        "sub": args.subject or args.tenant_key,
        "jti": license_key,
        "iat": int(now.timestamp()),
        "nbf": int(not_before.timestamp()),
        "exp": int(expires.timestamp()),
        "tenant_key": args.tenant_key,
        "deployment_id": args.deployment_id,
        "plan_key": args.plan_key,
        "features": parse_list(args.features, plan_features),
        "limits": parse_limits(args.limits, plan_limits),
        "customer_name": args.customer_name,
        "contract_reference": args.contract_reference,
        "license_schema": "beezaoffice.license/v1",
    }
    token = jwt.encode(claims, private_key, algorithm="EdDSA")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(token + "\n", encoding="utf-8")
    os.chmod(output_path, 0o600)

    summary_path = output_path.with_suffix(output_path.suffix + ".json")
    summary_path.write_text(
        json.dumps(
            {
                **claims,
                "iat": now.isoformat(),
                "nbf": not_before.isoformat(),
                "exp": expires.isoformat(),
                "token_file": str(output_path),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(summary_path, 0o600)
    print(f"License: {license_key}")
    print(f"Token: {output_path}")
    print(f"Summary: {summary_path}")
    print(f"Valid until: {expires.isoformat()}")


if __name__ == "__main__":
    main()
