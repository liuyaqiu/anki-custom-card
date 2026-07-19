from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from anki_custom_card.persistence.models import AnkiPublication, Job, Note


class PublicationNotFoundError(LookupError):
    pass


class PublicationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, note_id: str) -> AnkiPublication | None:
        return self.session.get(AnkiPublication, note_id)

    def ensure(self, note_id: str, *, deck: str, note_type: str) -> AnkiPublication:
        publication = self.get(note_id)
        if publication is None:
            publication = AnkiPublication(
                note_id=note_id, target_deck=deck, target_note_type=note_type, status="pending"
            )
            self.session.add(publication)
            self.session.flush()
        return publication

    def begin(self, note_id: str, *, target_version: int, now: datetime) -> AnkiPublication:
        result = self.session.execute(
            update(AnkiPublication)
            .where(AnkiPublication.note_id == note_id)
            .values(
                status="publishing",
                publishing_version=target_version,
                attempt_count=AnkiPublication.attempt_count + 1,
                last_attempt_at=now,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            raise PublicationNotFoundError(note_id)
        self.session.expire_all()
        return self.get(note_id)  # type: ignore[return-value]

    def succeed(
        self,
        note_id: str,
        *,
        target_version: int,
        anki_note_id: int,
        published_hash: str,
        observed_hash: str,
        now: datetime,
    ) -> AnkiPublication:
        note_version = self.session.scalar(select(Note.version).where(Note.id == note_id))
        status = "published" if note_version == target_version else "pending"
        self.session.execute(
            update(AnkiPublication)
            .where(AnkiPublication.note_id == note_id)
            .values(
                anki_note_id=anki_note_id,
                published_version=target_version,
                publishing_version=None,
                published_hash=published_hash,
                observed_anki_hash=observed_hash,
                status=status,
                published_at=now,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )
        )
        self.session.expire_all()
        return self.get(note_id)  # type: ignore[return-value]

    def fail(self, note_id: str, *, code: str, message: str, now: datetime) -> None:
        self.session.execute(
            update(AnkiPublication)
            .where(AnkiPublication.note_id == note_id)
            .values(
                status="failed",
                publishing_version=None,
                last_error_code=code,
                last_error_message=message,
                updated_at=now,
            )
        )

    def request_archive(self, note_id: str, *, now: datetime) -> bool:
        result = self.session.execute(
            update(Note)
            .where(Note.id == note_id, Note.status == "active")
            .values(status="archive_pending", updated_at=now)
        )
        if result.rowcount != 1:
            raise ValueError(f"Note {note_id} is not active")
        self.session.execute(
            update(Job)
            .where(Job.job_type == "publish", Job.aggregate_id == note_id, Job.status == "pending")
            .values(status="failed", last_error="superseded by archive", updated_at=now)
        )
        publication = self.get(note_id)
        if publication is None or publication.anki_note_id is None:
            if publication is not None:
                publication.status = "deleted"
                publication.updated_at = now
            self.session.execute(
                update(Note).where(Note.id == note_id).values(status="archived", updated_at=now)
            )
            return False
        publication.status = "deleting"
        publication.updated_at = now
        return True

    def complete_deletion(self, note_id: str, *, now: datetime) -> None:
        publication = self.get(note_id)
        if publication is None:
            raise PublicationNotFoundError(note_id)
        publication.status = "deleted"
        publication.last_error_code = None
        publication.last_error_message = None
        publication.updated_at = now
        self.session.execute(
            update(Note)
            .where(Note.id == note_id, Note.status == "archive_pending")
            .values(status="archived", updated_at=now)
        )

    def fail_deletion(self, note_id: str, *, code: str, message: str, now: datetime) -> None:
        self.session.execute(
            update(AnkiPublication)
            .where(AnkiPublication.note_id == note_id)
            .values(
                status="deletion_failed",
                last_error_code=code,
                last_error_message=message,
                updated_at=now,
            )
        )
