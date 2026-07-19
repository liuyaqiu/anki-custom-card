from pathlib import Path

import pytest
from sqlalchemy import text

from anki_custom_card.persistence.database import build_engine

pytestmark = pytest.mark.unit


def test_sqlite_engine_enables_integrity_and_concurrency_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    engine = build_engine(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    engine.dispose()

    assert foreign_keys == 1
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
