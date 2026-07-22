#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

APP_VERSION = "0.16.1"
PLAN_FEATURES = [
    "core.missions",
    "collaboration",
    "meetings",
    "governance",
    "registry",
    "scheduler",
    "evaluation",
    "sop",
    "protocol",
    "runtime.dispatch",
    "enterprise",
    "business",
    "marketplace",
    "white_label",
    "backup_dr",
    "siem",
    "metrics",
    "kubernetes",
]
PLAN_LIMITS = {
    "max_agents": 500,
    "max_concurrent_tasks": 100,
    "max_tenants": 10,
    "max_deployments": 4,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an ephemeral BeezaOffice 0.16.1 Agent Rooms Pilot license bundle."
    )
    parser.add_argument("--tenant-key", default="tenant:beeza")
    parser.add_argument("--deployment-id", default="deployment:pilot-gate")
    parser.add_argument("--customer-name", default="BeezaOffice Internal Pilot")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output-dir", default=".pilot-license")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    private_path = output_dir / "private.pem"
    public_path = output_dir / "public.pem"
    token_path = output_dir / "license.jwt"
    env_path = output_dir / "license.env"
    manifest_path = output_dir / "license-manifest.json"

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    os.chmod(private_path, 0o600)
    os.chmod(public_path, 0o644)

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=args.days)
    license_key = f"LIC-PILOT-{uuid4().hex[:16].upper()}"
    claims = {
        "iss": "beezaoffice-license",
        "aud": "beezaoffice",
        "sub": args.tenant_key,
        "jti": license_key,
        "iat": int(now.timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int(expires.timestamp()),
        "tenant_key": args.tenant_key,
        "deployment_id": args.deployment_id,
        "plan_key": "plan:enterprise",
        "features": PLAN_FEATURES,
        "limits": PLAN_LIMITS,
        "customer_name": args.customer_name,
        "contract_reference": f"PILOT-{now:%Y%m%d}",
        "license_schema": "beezaoffice.license/v1",
        "pilot_only": True,
    }
    token = jwt.encode(claims, private_pem.decode(), algorithm="EdDSA")
    token_path.write_text(token + "\n", encoding="utf-8")
    os.chmod(token_path, 0o600)

    escaped_public = public_pem.decode().strip().replace("\n", "\\n")
    env_path.write_text(
        "\n".join(
            [
                f"BEEZA_APP_VERSION={APP_VERSION}",
                "BEEZA_RELEASE_CHANNEL=pilot",
                "BEEZA_LICENSE_MODE=enforce",
                f"BEEZA_DEPLOYMENT_ID={args.deployment_id}",
                "BEEZA_LICENSE_ISSUER=beezaoffice-license",
                "BEEZA_LICENSE_AUDIENCE=beezaoffice",
                "BEEZA_LICENSE_ALGORITHMS=EdDSA",
                f"BEEZA_LICENSE_PUBLIC_KEY={escaped_public}",
                f"BEEZA_LICENSE_TOKEN={token}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)
    manifest_path.write_text(
        json.dumps(
            {
                "version": APP_VERSION,
                "release": "Agent Rooms",
                "license_key": license_key,
                "tenant_key": args.tenant_key,
                "deployment_id": args.deployment_id,
                "plan_key": "plan:enterprise",
                "issued_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "pilot_only": True,
                "files": {
                    "public_key": str(public_path),
                    "token": str(token_path),
                    "environment": str(env_path),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o600)
    print(manifest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
