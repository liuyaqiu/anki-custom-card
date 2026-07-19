import hashlib
import json
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from anki_custom_card.domain.notes import NoteCreate, NoteUpdate
from anki_custom_card.domain.words import clean_word_display, normalize_english_word
from anki_custom_card.persistence.models import Note, NoteRevision


class ConcurrentUpdateError(RuntimeError):
    pass


class NoteNotFoundError(LookupError):
    pass


REVISION_FIELDS = (
    "language",
    "word_display",
    "word_normalized",
    "word_idx",
    "variant",
    "domain",
    "part_of_speech",
    "source_sense_ids",
    "definition_en",
    "definition_zh",
    "example",
    "example_zh",
    "pronunciation",
    "collocations",
    "usage_notes",
    "extra",
    "status",
)


def revision_content(note: Note) -> dict[str, Any]:
    return {field: getattr(note, field) for field in REVISION_FIELDS}


def content_hash(content: dict[str, Any]) -> str:
    serialized = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


class NoteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, note_id: str) -> Note | None:
        return self.session.get(Note, note_id)

    def create(self, data: NoteCreate) -> Note:
        values = data.model_dump()
        values["word_display"] = clean_word_display(data.word_display)
        values["word_normalized"] = normalize_english_word(data.word_display)
        note = Note(**values)
        self.session.add(note)
        self.session.flush()
        self._add_revision(note)
        self.session.flush()
        return note

    def update(self, note_id: str, *, expected_version: int, changes: NoteUpdate) -> Note:
        changed_values = changes.changes()
        if not changed_values:
            raise ValueError("at least one Note field must change")

        next_version = expected_version + 1
        result = self.session.execute(
            update(Note)
            .where(Note.id == note_id, Note.version == expected_version, Note.status == "active")
            .values(**changed_values, version=next_version)
        )
        if result.rowcount != 1:
            raise ConcurrentUpdateError(
                f"Note {note_id} is not at expected version {expected_version}"
            )

        self.session.expire_all()
        note = self.session.get(Note, note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        self._add_revision(note)
        self.session.flush()
        return note

    def hard_delete(self, note_id: str) -> None:
        result = self.session.execute(delete(Note).where(Note.id == note_id))
        if result.rowcount != 1:
            raise NoteNotFoundError(note_id)

    def _add_revision(self, note: Note) -> None:
        content = revision_content(note)
        note.revisions.append(
            NoteRevision(
                version=note.version,
                content=content,
                content_hash=content_hash(content),
            )
        )
