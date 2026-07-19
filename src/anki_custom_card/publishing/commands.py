from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Job
from anki_custom_card.persistence.publication_repository import PublicationRepository
from anki_custom_card.publishing.note_type import NOTE_TYPE_NAME


def request_publish(
    session: Session,
    note_id: str,
    target_version: int,
    *,
    now: datetime,
    deck: str = "Anki Custom Card",
) -> Job:
    PublicationRepository(session).ensure(note_id, deck=deck, note_type=NOTE_TYPE_NAME)
    existing = session.scalar(
        select(Job).where(
            Job.job_type == "publish",
            Job.aggregate_id == note_id,
            Job.status.in_(("pending", "running")),
        )
    )
    if existing is None:
        return JobRepository(session).enqueue(
            job_type="publish", aggregate_id=note_id, target_version=target_version, now=now
        )
    if existing.status == "pending" and (existing.target_version or 0) < target_version:
        session.execute(
            update(Job)
            .where(Job.id == existing.id)
            .values(
                target_version=target_version,
                updated_at=now,
            )
        )
        session.refresh(existing)
    return existing


def request_archive(session: Session, note_id: str, *, now: datetime) -> bool:
    """Persist archive intent and, when needed, an idempotent remote deletion job."""
    repository = PublicationRepository(session)
    repository.ensure(note_id, deck="Anki Custom Card", note_type=NOTE_TYPE_NAME)
    needs_remote_delete = repository.request_archive(note_id, now=now)
    if needs_remote_delete:
        JobRepository(session).enqueue(job_type="delete_anki", aggregate_id=note_id, now=now)
    return needs_remote_delete


def request_inspection(session: Session, note_id: str, *, now: datetime) -> Job:
    existing = session.scalar(
        select(Job).where(
            Job.job_type == "inspect",
            Job.aggregate_id == note_id,
            Job.status.in_(("pending", "running")),
        )
    )
    if existing is not None:
        return existing
    return JobRepository(session).enqueue(job_type="inspect", aggregate_id=note_id, now=now)
