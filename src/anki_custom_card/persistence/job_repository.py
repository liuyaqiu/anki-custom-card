from datetime import datetime, timedelta

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from anki_custom_card.persistence.models import Job


class JobLeaseLostError(RuntimeError):
    pass


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        *,
        job_type: str,
        aggregate_id: str,
        payload: dict[str, object] | None = None,
        target_version: int | None = None,
        max_attempts: int = 5,
        now: datetime,
    ) -> Job:
        job = Job(
            job_type=job_type,
            aggregate_id=aggregate_id,
            payload=payload or {},
            target_version=target_version,
            max_attempts=max_attempts,
            available_at=now,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim(self, worker_id: str, now: datetime, lease_duration: timedelta) -> Job | None:
        self.session.execute(
            update(Job)
            .where(
                Job.status == "running",
                Job.lease_expires_at <= now,
                Job.attempts >= Job.max_attempts,
            )
            .values(
                status="failed",
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                last_error="lease expired after final attempt",
                updated_at=now,
            )
        )
        eligible = or_(
            and_(Job.status == "pending", Job.available_at <= now),
            and_(Job.status == "running", Job.lease_expires_at <= now),
        )
        candidate = (
            select(Job.id)
            .where(eligible, Job.attempts < Job.max_attempts)
            .order_by(Job.available_at, Job.created_at, Job.id)
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(Job)
            .where(Job.id == candidate)
            .values(
                status="running",
                locked_by=worker_id,
                locked_at=now,
                lease_expires_at=now + lease_duration,
                attempts=Job.attempts + 1,
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()

    def complete(self, job_id: str, *, worker_id: str, now: datetime) -> Job:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                status="succeeded",
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
            .returning(Job)
        )
        return self._owned_result(statement, job_id, worker_id)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error: str,
        retry_at: datetime,
        now: datetime,
        retryable: bool = True,
    ) -> Job:
        terminal = (Job.attempts >= Job.max_attempts) | (not retryable)
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                status=case((terminal, "failed"), else_="pending"),
                available_at=case((terminal, Job.available_at), else_=retry_at),
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                last_error=error,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
            .returning(Job)
        )
        return self._owned_result(statement, job_id, worker_id)

    def retry_failed(self, job_id: str, *, now: datetime) -> Job:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == "failed")
            .values(
                status="pending",
                attempts=0,
                available_at=now,
                last_error=None,
                locked_by=None,
                locked_at=None,
                lease_expires_at=None,
                updated_at=now,
            )
            .returning(Job)
        )
        job = self.session.scalars(statement).one_or_none()
        if job is None:
            raise ValueError(f"Job {job_id} is not failed")
        return job

    def _owned_result(self, statement: object, job_id: str, worker_id: str) -> Job:
        job = self.session.scalars(statement).one_or_none()  # type: ignore[arg-type]
        if job is None:
            raise JobLeaseLostError(f"worker {worker_id} does not own running job {job_id}")
        self.session.refresh(job)
        return job
