from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import commercial_service
import phase14_app
from business_models import BillingPlan, TenantSubscription
from commercial_models import CommercialLicense, FeatureEntitlement
from commercial_service import PLAN_FEATURES, PLAN_LIMITS
from enterprise_models import EnterpriseTenant
from main import utcnow

if commercial_service.LICENSE_MODE not in {"development", "warn", "enforce"}:
    raise RuntimeError("BEEZA_LICENSE_MODE must be development, warn or enforce")

_original_seed_commercial = commercial_service.seed_commercial
_original_license_state = commercial_service.license_state
_original_activate_license = commercial_service.activate_license
_original_current_license = commercial_service.current_license


def hardened_current_license(
    db: Session,
    tenant_key: str,
) -> CommercialLicense | None:
    row = _original_current_license(db, tenant_key)
    if (
        row is not None
        and row.status == "DEVELOPMENT"
        and commercial_service.LICENSE_MODE != "development"
    ):
        return None
    return row


def hardened_activate_license(
    db: Session,
    tenant_key: str,
    encoded: str,
    actor: str,
) -> CommercialLicense:
    digest = commercial_service.token_hash(encoded)
    existing = db.scalar(
        select(CommercialLicense).where(CommercialLicense.token_hash == digest)
    )
    if existing is not None and (
        existing.tenant_key != tenant_key
        or existing.deployment_id != commercial_service.DEPLOYMENT_ID
    ):
        raise ValueError("License token is already bound to another tenant or deployment")
    return _original_activate_license(db, tenant_key, encoded, actor)


def sync_contract_entitlements(db: Session, tenant_key: str) -> None:
    subscription = db.scalar(
        select(TenantSubscription).where(
            TenantSubscription.tenant_key == tenant_key,
            TenantSubscription.status == "ACTIVE",
        )
    )
    if subscription is None:
        return
    plan = db.scalar(
        select(BillingPlan).where(
            BillingPlan.plan_key == subscription.plan_key,
            BillingPlan.status == "ACTIVE",
        )
    )
    if plan is None:
        return
    commercial_service.set_entitlements(
        db,
        tenant_key,
        "CONTRACT",
        subscription.subscription_key,
        PLAN_FEATURES.get(plan.plan_key, []),
        PLAN_LIMITS.get(plan.plan_key, {}),
        subscription.starts_at,
        subscription.ends_at,
    )


def commercial_seed_with_contracts(db: Session) -> None:
    configured_token = commercial_service.LICENSE_TOKEN
    suppress_warn_token = (
        commercial_service.LICENSE_MODE == "warn" and bool(configured_token)
    )
    if suppress_warn_token:
        commercial_service.LICENSE_TOKEN = ""
    try:
        _original_seed_commercial(db)
    finally:
        if suppress_warn_token:
            commercial_service.LICENSE_TOKEN = configured_token

    tenant_keys = list(
        db.scalars(
            select(EnterpriseTenant.tenant_key).where(
                EnterpriseTenant.status == "ACTIVE"
            )
        ).all()
    )
    for tenant_key in tenant_keys:
        sync_contract_entitlements(db, tenant_key)
    db.commit()

    if configured_token and commercial_service.LICENSE_MODE != "development":
        try:
            hardened_activate_license(
                db,
                commercial_service.DEFAULT_TENANT,
                configured_token,
                "system:phase14",
            )
        except Exception:
            db.rollback()
            if commercial_service.LICENSE_MODE == "enforce":
                raise


def source_entitlements(
    db: Session,
    tenant_key: str,
    source: str,
) -> dict[str, FeatureEntitlement]:
    now = utcnow()
    rows = db.scalars(
        select(FeatureEntitlement).where(
            FeatureEntitlement.tenant_key == tenant_key,
            FeatureEntitlement.source == source,
            FeatureEntitlement.enabled.is_(True),
        )
    ).all()
    return {
        row.feature_key: row
        for row in rows
        if (row.valid_from is None or row.valid_from <= now)
        and (row.valid_until is None or row.valid_until > now)
    }


def effective_feature_contract(
    db: Session,
    tenant_key: str,
) -> tuple[set[str], dict[str, int], set[str], set[str]]:
    sync_contract_entitlements(db, tenant_key)
    db.commit()
    license_row = hardened_current_license(db, tenant_key)
    if license_row is None:
        return set(), {}, set(), set()
    license_features = set(license_row.features or [])
    license_limits = {
        str(key): int(value)
        for key, value in (license_row.limits or {}).items()
    }
    contract_rows = source_entitlements(db, tenant_key, "CONTRACT")
    contract_features = {
        key for key in contract_rows if not key.startswith("limit.")
    }
    effective_features = (
        license_features & contract_features
        if contract_features
        else license_features
    )
    effective_limits: dict[str, int] = {}
    all_limit_keys = set(license_limits) | {
        key.removeprefix("limit.")
        for key in contract_rows
        if key.startswith("limit.")
    }
    for key in all_limit_keys:
        candidates = []
        if key in license_limits and license_limits[key] > 0:
            candidates.append(license_limits[key])
        contract = contract_rows.get(f"limit.{key}")
        if contract and contract.limit_value and contract.limit_value > 0:
            candidates.append(int(contract.limit_value))
        if candidates:
            effective_limits[key] = min(candidates)
    return effective_features, effective_limits, license_features, contract_features


def contract_entitlement_allowed(
    db: Session,
    tenant_key: str,
    feature_key: str,
) -> bool:
    features, _, _, _ = effective_feature_contract(db, tenant_key)
    return feature_key in features


def contract_entitlement_limit(
    db: Session,
    tenant_key: str,
    limit_key: str,
    default: int = 0,
) -> int:
    _, limits, _, _ = effective_feature_contract(db, tenant_key)
    return int(limits.get(limit_key, default))


def contract_license_state(db: Session, tenant_key: str):
    state = _original_license_state(db, tenant_key)
    row = hardened_current_license(db, tenant_key)
    state["valid"] = row is not None
    state["allowed"] = row is not None or commercial_service.LICENSE_MODE in {
        "development",
        "warn",
    }
    state["license"] = commercial_service.license_view(row) if row else None
    state["warning"] = None if row else "No active verified commercial license"
    features, limits, licensed, contracted = effective_feature_contract(db, tenant_key)
    state["licensed_features"] = sorted(licensed)
    state["contract_features"] = sorted(contracted)
    state["features"] = sorted(features)
    state["limits"] = limits
    state["contract_enforced"] = bool(contracted)
    return state


commercial_service.current_license = hardened_current_license
commercial_service.activate_license = hardened_activate_license
commercial_service.seed_commercial = commercial_seed_with_contracts
commercial_service.entitlement_allowed = contract_entitlement_allowed
commercial_service.entitlement_limit = contract_entitlement_limit
commercial_service.license_state = contract_license_state
phase14_app.current_license = hardened_current_license
phase14_app.activate_license = hardened_activate_license
phase14_app.seed_commercial = commercial_seed_with_contracts
phase14_app.entitlement_allowed = contract_entitlement_allowed
phase14_app.entitlement_limit = contract_entitlement_limit
phase14_app.license_state = contract_license_state
