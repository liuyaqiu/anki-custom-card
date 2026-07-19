from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import AnkiPublication, Job, Note
from anki_custom_card.publishing.commands import request_publish
from anki_custom_card.publishing.inspection import AnkiInspectionService
from anki_custom_card.publishing.note_type import IncompatibleNoteTypeError
from anki_custom_card.publishing.service import DuplicateSourceIdError, PublicationService


class PublicationJobHandler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        service: PublicationService,
        inspection_service: AnkiInspectionService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.service = service
        self.inspection_service = inspection_service

    async def run(self, job_id: str, *, worker_id: str) -> Job:
        with self.session_factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.status != "running" or job.locked_by != worker_id:
                raise ValueError(f"worker {worker_id} does not own running job {job_id}")
            job_type = job.job_type
            note_id = job.aggregate_id
            target_version = job.target_version
            attempt = job.attempts
        try:
            if job_type == "publish":
                if target_version is None:
                    raise ValueError("publish job requires target_version")
                await self.service.publish(note_id, target_version)
            elif job_type == "delete_anki":
                await self.service.delete_archived(note_id)
            elif job_type == "inspect" and self.inspection_service is not None:
                await self.inspection_service.inspect(note_id)
            else:
                raise ValueError(f"unsupported publication job type: {job_type}")
        except Exception as error:
            now = datetime.now(UTC)
            retry_at = now + timedelta(seconds=min(300, 2 ** max(0, attempt - 1)))
            with self.session_factory.begin() as session:
                retryable = bool(
                    getattr(
                        error,
                        "retryable",
                        not isinstance(
                            error, (ValueError, DuplicateSourceIdError, IncompatibleNoteTypeError)
                        ),
                    )
                )
                return JobRepository(session).fail(
                    job_id,
                    worker_id=worker_id,
                    error=str(error),
                    retry_at=retry_at,
                    now=now,
                    retryable=retryable,
                )

        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            completed = JobRepository(session).complete(job_id, worker_id=worker_id, now=now)
            if job_type == "publish":
                note = session.get(Note, note_id)
                publication = session.get(AnkiPublication, note_id)
                if (
                    note is not None
                    and note.status == "active"
                    and publication is not None
                    and (publication.published_version or 0) < note.version
                ):
                    request_publish(
                        session, note_id, note.version, now=now, deck=publication.target_deck
                    )
            return completed
