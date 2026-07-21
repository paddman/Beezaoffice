from __future__ import annotations

import phase14_app
from main import app, engine

_original_start_commercial_layer = phase14_app.start_commercial_layer


def migrate_entitlement_source_constraint() -> None:
    if engine.dialect.name != "postgresql":
        return
    statement = """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_commercial_tenant_feature'
      ) THEN
        ALTER TABLE commercial_feature_entitlements
          DROP CONSTRAINT uq_commercial_tenant_feature;
      END IF;

      IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_commercial_tenant_feature_source'
      ) THEN
        ALTER TABLE commercial_feature_entitlements
          ADD CONSTRAINT uq_commercial_tenant_feature_source
          UNIQUE (tenant_key, feature_key, source);
      END IF;
    END $$;
    """
    with engine.begin() as connection:
        connection.exec_driver_sql(statement)


def hardened_start_commercial_layer() -> None:
    migrate_entitlement_source_constraint()
    _original_start_commercial_layer()


app.router.on_startup[:] = [
    hardened_start_commercial_layer
    if callback is _original_start_commercial_layer
    else callback
    for callback in app.router.on_startup
]
phase14_app.start_commercial_layer = hardened_start_commercial_layer
