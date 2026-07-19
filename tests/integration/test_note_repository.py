from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from anki_custom_card.domain.notes import NoteCreate, NoteUpdate
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.models import Artifact, Base, Draft, GenerationJob, NoteRevision
from anki_custom_card.persistence.note_repository import ConcurrentUpdateError, NoteRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'repository.db'}")
    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def create_note(session: Session, *, word: str = "Deploy", word_idx: int = 0) -> str:
    note = NoteRepository(session).create(
        NoteCreate(
            language="en",
            word_display=word,
            word_idx=word_idx,
            domain="it",
            definition_en="To release software to a target environment.",
            definition_zh="部署",
            example="The team will deploy the service after the review.",
            example_zh="团队将在评审后部署该服务。",
        )
    )
    session.commit()
    return note.id


def test_create_note_normalizes_word_and_writes_initial_revision(engine: Engine) -> None:
    with Session(engine) as session:
        note_id = create_note(session, word="  DEPLOY  ")
        note = NoteRepository(session).get(note_id)
        revision = session.get(NoteRevision, (note_id, 1))

        assert note is not None
        assert note.word_display == "DEPLOY"
        assert note.word_normalized == "deploy"
        assert note.word_idx == 0
        assert note.version == 1
        assert revision is not None
        assert revision.content["definition_en"] == note.definition_en
        assert revision.content_hash


def test_business_identity_is_unique(engine: Engine) -> None:
    with Session(engine) as session:
        create_note(session, word="Deploy")
        with pytest.raises(IntegrityError):
            NoteRepository(session).create(
                NoteCreate(
                    language="en",
                    word_display=" deploy ",
                    definition_en="A duplicate.",
                    definition_zh="重复",
                    example="We deploy it.",
                    example_zh="我们部署它。",
                )
            )


def test_same_word_can_use_another_word_index(engine: Engine) -> None:
    with Session(engine) as session:
        first_id = create_note(session, word_idx=0)
        second_id = create_note(session, word_idx=1)

        assert first_id != second_id


def test_update_uses_optimistic_version_and_writes_revision(engine: Engine) -> None:
    with Session(engine) as session:
        note_id = create_note(session)
        updated = NoteRepository(session).update(
            note_id,
            expected_version=1,
            changes=NoteUpdate(example="We deploy small changes several times a day."),
        )
        session.commit()

        assert updated.version == 2
        assert updated.example == "We deploy small changes several times a day."
        revision = session.get(NoteRevision, (note_id, 2))
        assert revision is not None
        assert revision.content["example"] == updated.example


def test_stale_update_is_rejected(engine: Engine) -> None:
    with Session(engine) as setup_session:
        note_id = create_note(setup_session)

    with Session(engine) as first_session, Session(engine) as second_session:
        first_repository = NoteRepository(first_session)
        second_repository = NoteRepository(second_session)
        assert first_repository.get(note_id).version == 1  # type: ignore[union-attr]
        assert second_repository.get(note_id).version == 1  # type: ignore[union-attr]

        second_repository.update(
            note_id,
            expected_version=1,
            changes=NoteUpdate(definition_zh="部署；发布"),  # noqa: RUF001 - natural Chinese text
        )
        second_session.commit()

        with pytest.raises(ConcurrentUpdateError):
            first_repository.update(
                note_id,
                expected_version=1,
                changes=NoteUpdate(definition_zh="投放"),
            )


def test_hard_delete_cascades_owned_generation_data(engine: Engine) -> None:
    with Session(engine) as session:
        note_id = create_note(session)
        job = GenerationJob(input_word="deploy", language="en", source_note_id=note_id)
        job.draft = Draft(content={"word": "deploy"})
        job.artifacts.append(
            Artifact(
                artifact_type="raw_response",
                provider="test-provider",
                structured_content={"entry": "deploy"},
            )
        )
        session.add(job)
        session.commit()

        NoteRepository(session).hard_delete(note_id)
        session.commit()

        assert session.scalar(select(func.count()).select_from(NoteRevision)) == 0
        assert session.scalar(select(func.count()).select_from(GenerationJob)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0
