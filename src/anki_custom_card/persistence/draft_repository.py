from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from anki_custom_card.domain.notes import NoteCreate, NoteUpdate
from anki_custom_card.generation.schemas import CardDraft
from anki_custom_card.persistence.models import Artifact, Draft, Note, NoteMedia
from anki_custom_card.persistence.note_repository import NoteRepository


class DraftConflictError(RuntimeError):
    pass


class DraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, draft_id: str) -> Draft | None:
        return self.session.get(Draft, draft_id)

    def create(self, generation_job_id: str, content: CardDraft) -> Draft:
        draft = Draft(
            generation_job_id=generation_job_id,
            content=content.model_dump(mode="json", by_alias=True),
        )
        self.session.add(draft)
        self.session.flush()
        return draft

    def update(self, draft_id: str, *, expected_version: int, content: CardDraft) -> Draft:
        result = self.session.execute(
            update(Draft)
            .where(
                Draft.id == draft_id,
                Draft.version == expected_version,
                Draft.status == "editable",
            )
            .values(
                content=content.model_dump(mode="json", by_alias=True),
                version=expected_version + 1,
            )
        )
        if result.rowcount != 1:
            raise DraftConflictError(f"Draft {draft_id} is stale or no longer editable")
        self.session.expire_all()
        draft = self.session.get(Draft, draft_id)
        if draft is None:  # pragma: no cover - row was updated in the same transaction
            raise LookupError(draft_id)
        return draft

    def confirm(
        self,
        draft_id: str,
        *,
        expected_version: int,
        expected_note_version: int | None = None,
        domain: Literal["general", "workplace", "it"],
        now: datetime,
    ) -> Note:
        draft = self.get(draft_id)
        if draft is None or draft.version != expected_version or draft.status != "editable":
            raise DraftConflictError(f"Draft {draft_id} is stale or no longer editable")
        content = CardDraft.model_validate(draft.content)
        fields = content.fields
        note_values = {
            "domain": domain,
            "part_of_speech": fields.part_of_speech,
            "source_sense_ids": content.selected_sense_ids,
            "definition_en": fields.definition_en,
            "definition_zh": fields.definition_zh,
            "example": fields.example,
            "example_zh": fields.example_zh,
            "pronunciation": fields.ipa,
            "collocations": [{"text": value} for value in fields.collocations],
            "usage_notes": fields.usage_note,
        }
        source_note_id = draft.generation_job.source_note_id
        note_repository = NoteRepository(self.session)
        if source_note_id is None:
            note = note_repository.create(
                NoteCreate(
                    language=draft.generation_job.language,
                    word_display=content.word,
                    word_idx=content.word_idx,
                    **note_values,
                )
            )
        else:
            if expected_note_version is None:
                raise ValueError("expected_note_version is required when updating a Note")
            note = note_repository.update(
                source_note_id,
                expected_version=expected_note_version,
                changes=NoteUpdate(**note_values),
            )
        artifacts = self.session.scalars(
            select(Artifact).where(
                Artifact.generation_job_id == draft.generation_job_id,
                Artifact.artifact_type.in_(("word_audio", "example_audio")),
                Artifact.media_id.is_not(None),
            )
        )
        for artifact in artifacts:
            self.session.execute(
                sqlite_insert(NoteMedia)
                .values(
                    note_id=note.id,
                    usage=artifact.artifact_type,
                    media_id=artifact.media_id,
                )
                .on_conflict_do_update(
                    index_elements=[NoteMedia.note_id, NoteMedia.usage],
                    set_={"media_id": artifact.media_id},
                )
            )
        result = self.session.execute(
            update(Draft)
            .where(
                Draft.id == draft_id,
                Draft.version == expected_version,
                Draft.status == "editable",
            )
            .values(
                status="confirmed",
                version=expected_version + 1,
                confirmed_note_id=note.id,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            raise DraftConflictError(f"Draft {draft_id} changed during confirmation")
        self.session.flush()
        return note
