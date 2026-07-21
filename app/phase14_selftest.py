from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import commercial_service
from commercial_license_hardening import strict_verify_license_token


def issue_test_token(
    private_pem: str,
    deployment_id: str,
    tenant_key: str = "tenant:test",
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "beezaoffice-license-test",
        "aud": "beezaoffice-test",
        "sub": tenant_key,
        "jti": f"LIC-TEST-{uuid4().hex[:12].upper()}",
        "iat": int(now.timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "tenant_key": tenant_key,
        "deployment_id": deployment_id,
        "plan_key": "plan:enterprise",
        "features": commercial_service.PLAN_FEATURES["plan:enterprise"],
        "limits": commercial_service.PLAN_LIMITS["plan:enterprise"],
    }
    return jwt.encode(claims, private_pem, algorithm="EdDSA")


def run() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    original = {
        "public_key": commercial_service.LICENSE_PUBLIC_KEY,
        "issuer": commercial_service.LICENSE_ISSUER,
        "audience": commercial_service.LICENSE_AUDIENCE,
        "algorithms": commercial_service.LICENSE_ALGORITHMS,
        "deployment_id": commercial_service.DEPLOYMENT_ID,
    }
    try:
        commercial_service.LICENSE_PUBLIC_KEY = public_pem
        commercial_service.LICENSE_ISSUER = "beezaoffice-license-test"
        commercial_service.LICENSE_AUDIENCE = "beezaoffice-test"
        commercial_service.LICENSE_ALGORITHMS = ["EdDSA"]
        commercial_service.DEPLOYMENT_ID = "deployment:test"

        token = issue_test_token(private_pem, "deployment:test")
        header, claims = strict_verify_license_token(token)
        assert header["alg"] == "EdDSA"
        assert claims["tenant_key"] == "tenant:test"
        assert claims["deployment_id"] == "deployment:test"
        assert claims["plan_key"] == "plan:enterprise"

        wrong_deployment = issue_test_token(private_pem, "deployment:wrong")
        try:
            strict_verify_license_token(wrong_deployment)
        except ValueError as exc:
            assert "different deployment" in str(exc)
        else:
            raise AssertionError("Deployment-bound license validation did not fail")

        unsupported = jwt.encode(
            {
                **claims,
                "jti": f"LIC-TEST-{uuid4().hex[:12].upper()}",
                "features": ["unsupported.feature"],
            },
            private_pem,
            algorithm="EdDSA",
        )
        try:
            strict_verify_license_token(unsupported)
        except ValueError as exc:
            assert "unsupported" in str(exc)
        else:
            raise AssertionError("Unsupported feature validation did not fail")
    finally:
        commercial_service.LICENSE_PUBLIC_KEY = original["public_key"]
        commercial_service.LICENSE_ISSUER = original["issuer"]
        commercial_service.LICENSE_AUDIENCE = original["audience"]
        commercial_service.LICENSE_ALGORITHMS = original["algorithms"]
        commercial_service.DEPLOYMENT_ID = original["deployment_id"]


if __name__ == "__main__":
    run()
    print("Phase 14 license self-test passed")
