"""Add pilot-program and gate-evidence tables for the 0.16.0 release.

Revision ID: 20260722_0002
Revises: 20260721_0001
Create Date: 2026-07-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from pilot_models import PilotGateEvidence, PilotProgram

revision: str = "20260722_0002"
down_revision: Union[str, Sequence[str], None] = "20260721_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    PilotProgram.__table__.create(bind=bind, checkfirst=True)
    PilotGateEvidence.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Pilot evidence is operational audit data. Downgrades are non-destructive;
    # only the Alembic revision marker moves back.
    pass
