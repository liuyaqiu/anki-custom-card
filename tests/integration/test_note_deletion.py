from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from anki_custom_card.deletion import ArchivedNoteRequiredError, NoteDeletionService
from anki_custom_card.domain.notes import NoteCreate
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import (
    Artifact,
    Base,
    Draft,
    GenerationJob,
    Job,
    Media,
    Note,
    NoteRevision,
    SpeechCacheEntry,
)
from anki_custom_card.persistence.note_repository import NoteRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'deletion.db'}")
    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def test_permanent_deletion_requires_archived_note_and_removes_owned_data(
    engine: Engine, tmp_path: Path
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        note = NoteRepository(session).create(
            NoteCreate(
                language="en",
                word_display="dilute",
                definition_en="To make something weaker.",
                definition_zh="稀释",
                example="Do not dilute the message.",
                example_zh="不要削弱信息。",
            )
        )
        note_id = note.id
        media = MediaRepository(session, store).add_and_link(
            note_id,
            content=b"ID3audio",
            media_type="audio",
            mime_type="audio/mpeg",
            usage="word_audio",
        )
        media_path = media.relative_path
        session.add(
            SpeechCacheEntry(
                cache_key="speech-key",
                provider="azure",
                config_version="1",
                text="dilute",
                locale="en-US",
                voice="en-US-AvaMultilingualNeural",
                ssml="<speak>dilute</speak>",
                output_format="mp3",
                media_id=media.id,
            )
        )
        generation = GenerationJob(input_word="dilute", language="en", status="succeeded")
        generation.draft = Draft(content={}, confirmed_note_id=note_id)
        generation.artifacts.append(
            Artifact(
                artifact_type="word_audio",
                provider="azure",
                media_id=media.id,
            )
        )
        session.add(generation)
        session.flush()
        session.add_all(
            [
                Job(
                    job_type="generate",
                    aggregate_id=generation.id,
                    status="succeeded",
                    available_at=datetime.now(UTC),
                ),
                Job(
                    job_type="delete_anki",
                    aggregate_id=note_id,
                    status="succeeded",
                    available_at=datetime.now(UTC),
                ),
            ]
        )

    service = NoteDeletionService(factory, store)
    with pytest.raises(ArchivedNoteRequiredError):
        service.delete(note_id)

    with factory.begin() as session:
        session.get(Note, note_id).status = "archived"  # type: ignore[union-attr]
    service.delete(note_id)

    with factory() as session:
        for model in (
            Note,
            NoteRevision,
            GenerationJob,
            Draft,
            Artifact,
            Job,
            SpeechCacheEntry,
            Media,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    assert not (store.root / media_path).exists()
