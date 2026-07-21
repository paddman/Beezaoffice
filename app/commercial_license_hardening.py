from __future__ import annotations

from typing import Any

import jwt

import commercial_service


def strict_verify_license_token(encoded: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not commercial_service.LICENSE_PUBLIC_KEY:
        raise ValueError("BEEZA_LICENSE_PUBLIC_KEY is not configured")
    header = jwt.get_unverified_header(encoded)
    algorithm = str(header.get("alg") or "")
    if algorithm not in commercial_service.LICENSE_ALGORITHMS:
        raise ValueError(f"License algorithm {algorithm or 'missing'} is not allowed")
    claims = jwt.decode(
        encoded,
        commercial_service.LICENSE_PUBLIC_KEY,
        algorithms=commercial_service.LICENSE_ALGORITHMS,
        audience=commercial_service.LICENSE_AUDIENCE,
        issuer=commercial_service.LICENSE_ISSUER,
        options={
            "require": [
                "exp",
                "iat",
                "nbf",
                "jti",
                "tenant_key",
                "deployment_id",
                "plan_key",
                "features",
                "limits",
            ]
        },
    )
    if claims.get("deployment_id") != commercial_service.DEPLOYMENT_ID:
        raise ValueError("License is bound to a different deployment")
    if not isinstance(claims.get("tenant_key"), str) or not claims["tenant_key"]:
        raise ValueError("License tenant_key is invalid")
    if not isinstance(claims.get("jti"), str) or not 3 <= len(claims["jti"]) <= 120:
        raise ValueError("License jti is invalid")
    plan_key = claims.get("plan_key")
    if plan_key not in commercial_service.PLAN_FEATURES:
        raise ValueError("License plan_key is not supported")
    allowed_features = set(commercial_service.PLAN_FEATURES[plan_key])
    features = claims.get("features")
    if not isinstance(features, list) or not all(
        isinstance(item, str) and item in allowed_features
        for item in features
    ):
        raise ValueError("License features exceed the selected plan")
    limits = claims.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("License limits must be an object")
    plan_limits = commercial_service.PLAN_LIMITS[plan_key]
    for key, value in limits.items():
        if (
            key not in plan_limits
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > plan_limits[key]
        ):
            raise ValueError(f"License limit {key} is invalid for {plan_key}")
    return header, claims


commercial_service.verify_license_token = strict_verify_license_token
