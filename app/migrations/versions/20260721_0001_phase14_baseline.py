"""Adopt the complete Phase 14 schema without destructive table recreation.

Revision ID: 20260721_0001
Revises: None
Create Date: 2026-07-21
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Register complete metadata before create_all.
import business_models  # noqa: F401
import collaboration_models  # noqa: F401
import commercial_models  # noqa: F401
import enterprise_models  # noqa: F401
import evaluation_models  # noqa: F401
import governance_models  # noqa: F401
import meeting_models  # noqa: F401
import protocol_models  # noqa: F401
import registry_models  # noqa: F401
import scheduler_models  # noqa: F401
import sop_models  # noqa: F401
from main import Base

revision: str = "20260721_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_commercial_tenant_feature'
              ) THEN
                ALTER TABLE commercial_feature_entitlements
                  DROP CONSTRAINT uq_commercial_tenant_feature;
              END IF;

              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_commercial_tenant_feature_source'
              ) THEN
                ALTER TABLE commercial_feature_entitlements
                  ADD CONSTRAINT uq_commercial_tenant_feature_source
                  UNIQUE (tenant_key, feature_key, source);
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Baseline adoption is deliberately non-destructive. Downgrade only moves the
    # Alembic revision marker; it never drops customer data or Phase 1–14 tables.
    pass
