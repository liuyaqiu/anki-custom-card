from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from anki_custom_card.persistence.database import build_engine

pytestmark = pytest.mark.integration


def test_initial_migration_builds_expected_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = build_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    generation_columns = {item["name"] for item in inspector.get_columns("generation_jobs")}
    generation_uniques = {
        item["name"] for item in inspector.get_unique_constraints("generation_jobs")
    }
    engine.dispose()

    assert {
        "alembic_version",
        "anki_publications",
        "artifacts",
        "dictionary_cache_entries",
        "drafts",
        "generation_jobs",
        "jobs",
        "media",
        "note_media",
        "note_revisions",
        "notes",
        "speech_cache_entries",
    } <= table_names
    assert "request_key" in generation_columns
    assert "uq_generation_jobs_request_key" in generation_uniques

    command.downgrade(config, "base")
    engine = build_engine(f"sqlite:///{database_path}")
    assert not (
        {
            "artifacts",
            "anki_publications",
            "dictionary_cache_entries",
            "drafts",
            "generation_jobs",
            "jobs",
            "media",
            "note_media",
            "note_revisions",
            "notes",
            "speech_cache_entries",
        }
        & set(inspect(engine).get_table_names())
    )
    engine.dispose()

    command.upgrade(config, "head")
    engine = build_engine(f"sqlite:///{database_path}")
    assert "notes" in inspect(engine).get_table_names()
    engine.dispose()
