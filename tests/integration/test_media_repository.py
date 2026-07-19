from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from anki_custom_card.domain.notes import NoteCreate
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import Base, Media, NoteMedia
from anki_custom_card.persistence.note_repository import NoteRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'media.db'}")
    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def create_note(session: Session, word: str) -> str:
    note = NoteRepository(session).create(
        NoteCreate(
            word_display=word,
            definition_en=f"Definition of {word}.",
            definition_zh="释义",
            example=f"Use {word} in an IT project.",
            example_zh="例句。",
        )
    )
    session.commit()
    return note.id


def test_media_is_deduplicated_and_garbage_collected_after_last_reference(
    engine: Engine, tmp_path: Path
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    content = b"shared-audio"

    with Session(engine) as session:
        first_note_id = create_note(session, "deploy")
        second_note_id = create_note(session, "rollback")
        repository = MediaRepository(session, store)

        first_media = repository.add_and_link(
            first_note_id,
            content=content,
            media_type="audio",
            mime_type="audio/mpeg",
            usage="word_audio",
        )
        second_media = repository.add_and_link(
            second_note_id,
            content=content,
            media_type="audio",
            mime_type="audio/mpeg",
            usage="word_audio",
        )
        session.commit()

        assert first_media.id == second_media.id
        assert session.scalar(select(func.count()).select_from(Media)) == 1
        assert session.scalar(select(func.count()).select_from(NoteMedia)) == 2

        NoteRepository(session).hard_delete(first_note_id)
        session.commit()
        assert repository.delete_unreferenced() == []

        NoteRepository(session).hard_delete(second_note_id)
        session.commit()
        paths = repository.delete_unreferenced()
        session.commit()
        repository.delete_files(paths)

        assert session.scalar(select(func.count()).select_from(Media)) == 0
        assert not (tmp_path / "media" / first_media.relative_path).exists()


def test_one_note_cannot_link_two_media_items_to_same_usage(engine: Engine, tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")

    with Session(engine) as session:
        note_id = create_note(session, "deploy")
        repository = MediaRepository(session, store)
        repository.add_and_link(
            note_id,
            content=b"first",
            media_type="audio",
            mime_type="audio/mpeg",
            usage="word_audio",
        )

        with pytest.raises(ValueError, match="already has media for usage"):
            repository.add_and_link(
                note_id,
                content=b"second",
                media_type="audio",
                mime_type="audio/mpeg",
                usage="word_audio",
            )
