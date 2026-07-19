from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from anki_custom_card.domain.notes import NoteCreate
from anki_custom_card.generation.schemas import CardDraft
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.draft_repository import (
    DraftConflictError,
    DraftRepository,
)
from anki_custom_card.persistence.generation_repository import GenerationRepository
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import (
    AnkiPublication,
    Artifact,
    Base,
    Job,
    NoteMedia,
    NoteRevision,
)
from anki_custom_card.persistence.note_repository import NoteRepository

pytestmark = pytest.mark.integration


def draft_content(example: str = "We automated the deployment.") -> CardDraft:
    return CardDraft.model_validate(
        {
            "schema_version": 1,
            "word": "deployment",
            "word_idx": 0,
            "selected_sense_ids": ["noun.it.release"],
            "fields": {
                "word": "deployment",
                "part_of_speech": "noun",
                "definition_en": "The process of making software available for use.",
                "definition_zh": "部署",
                "example": example,
                "example_zh": "我们实现了部署自动化。",
                "collocations": ["automated deployment"],
            },
            "speech": {"word_text": "deployment", "example_text": example},
        }
    )


def test_draft_edit_uses_optimistic_version_and_confirmation_is_atomic(tmp_path: Path) -> None:
    engine: Engine = build_engine(f"sqlite:///{tmp_path / 'draft.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    store = ContentAddressedMediaStore(tmp_path / "media")
    with Session(engine) as session:
        job = GenerationRepository(session).create_job("deployment", "en", now=now)
        draft = DraftRepository(session).create(job.id, draft_content())
        media_repository = MediaRepository(session, store)
        word_audio = media_repository.add(
            content=b"word", media_type="audio", mime_type="audio/mpeg"
        )
        example_audio = media_repository.add(
            content=b"example", media_type="audio", mime_type="audio/mpeg"
        )
        session.add_all(
            [
                Artifact(
                    generation_job_id=job.id,
                    artifact_type="word_audio",
                    provider="azure_speech",
                    media_id=word_audio.id,
                ),
                Artifact(
                    generation_job_id=job.id,
                    artifact_type="example_audio",
                    provider="azure_speech",
                    media_id=example_audio.id,
                ),
            ]
        )
        session.commit()

        edited = DraftRepository(session).update(
            draft.id,
            expected_version=1,
            content=draft_content("The deployment completed without downtime."),
        )
        assert edited.version == 2
        session.commit()
        with pytest.raises(DraftConflictError):
            DraftRepository(session).update(draft.id, expected_version=1, content=draft_content())
        session.rollback()

        note = DraftRepository(session).confirm(draft.id, expected_version=2, domain="it", now=now)
        session.commit()

        assert note.version == 1
        assert note.example == "The deployment completed without downtime."
        assert session.get(NoteRevision, (note.id, 1)) is not None
        assert session.scalar(select(func.count()).select_from(NoteMedia)) == 2
        assert DraftRepository(session).get(draft.id).status == "confirmed"  # type: ignore[union-attr]
        assert session.get(AnkiPublication, note.id).status == "pending"  # type: ignore[union-attr]
        publish_job = session.scalar(select(Job).where(Job.aggregate_id == note.id))
        assert publish_job is not None
        assert publish_job.job_type == "publish"
        assert publish_job.target_version == 1
    engine.dispose()


def test_confirming_regenerated_draft_updates_existing_note(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'update-draft.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        note = NoteRepository(session).create(
            NoteCreate(
                word_display="deployment",
                domain="it",
                definition_en="An old definition.",
                definition_zh="部署",
                example="The old deployment failed.",
                example_zh="旧部署失败了。",
            )
        )
        job = GenerationRepository(session).create_job("deployment", "en", now=now)
        job.source_note_id = note.id
        draft = DraftRepository(session).create(
            job.id, draft_content("The deployment completed without downtime.")
        )
        session.commit()

        updated = DraftRepository(session).confirm(
            draft.id,
            expected_version=1,
            expected_note_version=1,
            domain="it",
            now=now,
        )
        session.commit()

        assert updated.id == note.id
        assert updated.version == 2
        assert session.get(NoteRevision, (note.id, 2)) is not None
        publish_job = session.scalar(select(Job).where(Job.aggregate_id == note.id))
        assert publish_job is not None and publish_job.target_version == 2
    engine.dispose()
