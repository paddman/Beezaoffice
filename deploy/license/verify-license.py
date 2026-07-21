#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import jwt


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a BeezaOffice commercial license JWT.")
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--issuer", default="beezaoffice-license")
    parser.add_argument("--audience", default="beezaoffice")
    parser.add_argument("--tenant-key")
    parser.add_argument("--deployment-id")
    args = parser.parse_args()

    public_key = Path(args.public_key).read_text(encoding="utf-8")
    token = Path(args.token).read_text(encoding="utf-8").strip()
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["EdDSA"],
        audience=args.audience,
        issuer=args.issuer,
        options={"require": ["exp", "iat", "jti", "tenant_key", "deployment_id"]},
    )
    if args.tenant_key and claims.get("tenant_key") != args.tenant_key:
        raise SystemExit("License tenant does not match")
    if args.deployment_id and claims.get("deployment_id") != args.deployment_id:
        raise SystemExit("License deployment does not match")
    print(json.dumps(claims, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
