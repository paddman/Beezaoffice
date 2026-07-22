"""Add Agent Rooms and Room Notes for release 0.16.1.

Revision ID: 20260722_0003
Revises: 20260722_0002
Create Date: 2026-07-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from agent_room_models import AgentRoom, AgentRoomNote

revision: str = "20260722_0003"
down_revision: Union[str, Sequence[str], None] = "20260722_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    AgentRoom.__table__.create(bind=bind, checkfirst=True)
    AgentRoomNote.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Room notes may contain operational memory. Keep the tables and only move
    # the Alembic revision marker during a controlled application rollback.
    pass
