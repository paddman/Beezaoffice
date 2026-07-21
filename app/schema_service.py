from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

ALEMBIC_CONFIG = Path(__file__).resolve().parent / "alembic.ini"


def alembic_config() -> Config:
    return Config(str(ALEMBIC_CONFIG))


def expected_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def schema_status(engine: Engine) -> dict[str, Any]:
    expected = expected_revision()
    current = current_revision(engine)
    return {
        "managed": current is not None,
        "current_revision": current,
        "expected_revision": expected,
        "up_to_date": bool(expected and current == expected),
        "config": str(ALEMBIC_CONFIG),
    }
