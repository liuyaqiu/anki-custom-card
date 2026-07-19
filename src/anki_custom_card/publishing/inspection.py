from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.persistence.models import (
    AnkiPublication,
    Media,
    Note,
    NoteMedia,
    NoteRevision,
)
from anki_custom_card.publishing.ports import AnkiGateway
from anki_custom_card.publishing.service import fields_hash, render_fields


@dataclass(frozen=True, slots=True)
class InspectionResult:
    status: str
    changed_fields: tuple[str, ...] = ()


class AnkiInspectionService:
    def __init__(self, session_factory: sessionmaker[Session], gateway: AnkiGateway) -> None:
        self.session_factory = session_factory
        self.gateway = gateway

    async def inspect(self, note_id: str) -> InspectionResult:
        with self.session_factory() as session:
            note = session.get(Note, note_id)
            publication = session.get(AnkiPublication, note_id)
            if note is None or publication is None:
                raise LookupError(note_id)
            if note.status != "active":
                return InspectionResult(publication.status)
            anki_note_id = publication.anki_note_id
            published_version = publication.published_version
            expected = self._expected_fields(session, note_id, published_version)

        info = await self.gateway.notes_info([anki_note_id]) if anki_note_id is not None else []
        now = datetime.now(UTC)
        if not info:
            with self.session_factory.begin() as session:
                session.execute(
                    update(AnkiPublication)
                    .where(AnkiPublication.note_id == note_id)
                    .values(status="missing", observed_anki_hash=None, updated_at=now)
                )
            return InspectionResult("missing")

        remote = {
            name: str(value.get("value", "")) for name, value in info[0].get("fields", {}).items()
        }
        observed_hash = fields_hash(remote)
        changed = tuple(
            sorted(
                name
                for name in set(expected) | set(remote)
                if expected.get(name) != remote.get(name)
            )
        )
        status = "drifted" if changed else "published"
        with self.session_factory.begin() as session:
            session.execute(
                update(AnkiPublication)
                .where(AnkiPublication.note_id == note_id)
                .values(status=status, observed_anki_hash=observed_hash, updated_at=now)
            )
        return InspectionResult(status, changed)

    def _expected_fields(
        self, session: Session, note_id: str, version: int | None
    ) -> dict[str, str]:
        if version is None:
            return {}
        revision = session.get(NoteRevision, (note_id, version))
        if revision is None:
            raise LookupError(f"Note {note_id} revision {version} was not found")
        rows = session.execute(
            select(NoteMedia.usage, Media.sha256, Media.relative_path)
            .join(Media, Media.id == NoteMedia.media_id)
            .where(NoteMedia.note_id == note_id)
        )
        media_names = {
            usage: f"acc_{sha256}{Path(relative_path).suffix}"
            for usage, sha256, relative_path in rows
        }
        return render_fields(note_id, dict(revision.content), media_names)
