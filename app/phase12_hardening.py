from __future__ import annotations

import re
from typing import Callable

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import PyJWKClient
from sqlalchemy import select

import enterprise_service
import governance_service
import phase12_app
import phase12_runtime
from enterprise_models import BackupRun, EnterpriseApiKey, IdentityProvider, SIEMSink
from main import SessionLocal, app


_ORIGINAL_PERMISSION = governance_service.permission_for_request
_EXTERNAL_EXECUTION = [
    re.compile(r"^/message:send$"),
    re.compile(r"^/v1/chat/completions$"),
    re.compile(r"^/hooks/[^/]+$"),
    re.compile(r"^/tasks/[^/:]+:cancel$"),
]


def enterprise_permission_for_request(method: str, path: str) -> str:
    if method.upper() == "POST" and any(pattern.match(path) for pattern in _EXTERNAL_EXECUTION):
        return "protocol:use"
    if method.upper() == "POST" and path == "/mcp":
        return "protocol:use"
    return _ORIGINAL_PERMISSION(method, path)


governance_service.permission_for_request = enterprise_permission_for_request
phase12_runtime.permission_for_request = enterprise_permission_for_request


def hardened_verify_oidc_token(provider: IdentityProvider, encoded: str):
    if provider.provider_type != "OIDC" or not provider.enabled:
        raise ValueError("OIDC provider is disabled")
    if not provider.issuer_url or not provider.jwks_uri:
        raise ValueError("OIDC issuer and JWKS URI are required")
    audience = provider.audience or provider.client_id
    signing_key = PyJWKClient(provider.jwks_uri).get_signing_key_from_jwt(encoded).key
    return jwt.decode(
        encoded,
        signing_key,
        algorithms=provider.allowed_algorithms or ["RS256"],
        audience=audience or None,
        issuer=provider.issuer_url,
        options={
            "require": [provider.subject_claim, "exp", "iat"],
            "verify_aud": bool(audience),
            "verify_iss": True,
        },
    )


enterprise_service.verify_oidc_token = hardened_verify_oidc_token
phase12_app.verify_oidc_token = hardened_verify_oidc_token


@app.middleware("http")
async def tenant_owned_enterprise_controls(request: Request, call_next: Callable):
    path = request.url.path
    tenant_key = request.headers.get("X-Beeza-Tenant", enterprise_service.DEFAULT_TENANT)
    lookup = None
    match = re.match(r"^/api/enterprise/api-keys/([^/]+)$", path)
    if match:
        lookup = (EnterpriseApiKey, EnterpriseApiKey.key_id, match.group(1))
    match = re.match(r"^/api/enterprise/backup/runs/([^/]+)/complete$", path)
    if match:
        lookup = (BackupRun, BackupRun.run_key, match.group(1))
    match = re.match(r"^/api/enterprise/siem/sinks/([^/]+)/checkpoint$", path)
    if match:
        lookup = (SIEMSink, SIEMSink.sink_key, match.group(1))
    if lookup:
        model, column, key = lookup
        with SessionLocal() as db:
            owner = db.scalar(select(model.tenant_key).where(column == key))
            if owner is not None and owner != tenant_key:
                return JSONResponse(status_code=404, content={"detail": "Enterprise resource not found"})
    return await call_next(request)
