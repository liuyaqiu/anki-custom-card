from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from anki_custom_card.generation.cache_keys import DictionaryCacheIdentity
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.dictionary_cache_repository import DictionaryCacheRepository
from anki_custom_card.persistence.models import Base, DictionaryCacheEntry

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'dictionary.db'}")
    Base.metadata.create_all(database_engine)
    return database_engine


def identity() -> DictionaryCacheIdentity:
    return DictionaryCacheIdentity(
        provider="openai",
        provider_dataset="synthetic_dictionary",
        normalized_query={"language": "en", "normalized_word": "deployment"},
        provider_config_version="1",
        prompt_version="dictionary-v1",
        schema_version=1,
        model="gpt-5.6-luna",
    )


def test_cache_put_is_idempotent_and_active_entry_can_be_loaded(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    payload = {"schema_version": 1, "entries": [{"headword": "deployment"}]}

    with Session(engine) as session:
        repository = DictionaryCacheRepository(session)
        first = repository.put(identity(), payload, source_entry_ids=["synthetic:noun:1"], now=now)
        second = repository.put(identity(), payload, source_entry_ids=["synthetic:noun:1"], now=now)
        session.commit()

        assert first.id == second.id
        assert first.model == "gpt-5.6-luna"
        assert first.prompt_version == "dictionary-v1"
        assert first.schema_version == 1
        assert repository.get(identity().request_key).response_payload == payload  # type: ignore[union-attr]
        assert session.scalar(select(func.count()).select_from(DictionaryCacheEntry)) == 1


def test_invalidated_cache_entry_is_not_returned(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = DictionaryCacheRepository(session)
        entry = repository.put(identity(), {"schema_version": 1}, source_entry_ids=[], now=now)
        repository.invalidate(entry.id, now=now)
        session.commit()

        assert repository.get(identity().request_key) is None
