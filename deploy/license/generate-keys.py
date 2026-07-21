#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def write_file(path: Path, content: bytes, mode: int, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"Refusing to overwrite {path}; use --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.chmod(path, mode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an offline BeezaOffice Ed25519 commercial-license key pair."
    )
    parser.add_argument("--private-key", default="beeza-license-private.pem")
    parser.add_argument("--public-key", default="beeza-license-public.pem")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

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

    private_path = Path(args.private_key).resolve()
    public_path = Path(args.public_key).resolve()
    write_file(private_path, private_pem, 0o600, args.force)
    write_file(public_path, public_pem, 0o644, args.force)
    print(f"Private signing key: {private_path}")
    print(f"Public verification key: {public_path}")
    print("Keep the private key offline; deploy only the public key to BeezaOffice.")


if __name__ == "__main__":
    main()
