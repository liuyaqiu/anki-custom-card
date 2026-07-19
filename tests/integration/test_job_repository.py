from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.job_repository import JobLeaseLostError, JobRepository
from anki_custom_card.persistence.models import Base

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def test_two_workers_cannot_claim_the_same_job(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as setup_session:
        job = JobRepository(setup_session).enqueue(
            job_type="publish", aggregate_id="note-1", payload={"version": 1}, now=now
        )
        setup_session.commit()
        job_id = job.id

    with Session(engine) as first_session, Session(engine) as second_session:
        first = JobRepository(first_session).claim(
            worker_id="worker-1", now=now, lease_duration=timedelta(seconds=30)
        )
        first_session.commit()
        second = JobRepository(second_session).claim(
            worker_id="worker-2", now=now, lease_duration=timedelta(seconds=30)
        )

        assert first is not None
        assert first.id == job_id
        assert first.locked_by == "worker-1"
        assert first.attempts == 1
        assert second is None


def test_expired_lease_can_be_reclaimed(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = JobRepository(session)
        repository.enqueue(job_type="generate", aggregate_id="generation-1", now=now)
        session.commit()

        first = repository.claim(
            worker_id="worker-1", now=now, lease_duration=timedelta(seconds=10)
        )
        session.commit()
        assert first is not None

        reclaimed = repository.claim(
            worker_id="worker-2",
            now=now + timedelta(seconds=11),
            lease_duration=timedelta(seconds=10),
        )
        session.commit()

        assert reclaimed is not None
        assert reclaimed.id == first.id
        assert reclaimed.locked_by == "worker-2"
        assert reclaimed.attempts == 2


def test_only_lease_owner_can_complete_job(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = JobRepository(session)
        repository.enqueue(job_type="inspect", aggregate_id="note-1", now=now)
        session.commit()
        job = repository.claim(worker_id="worker-1", now=now, lease_duration=timedelta(seconds=30))
        session.commit()
        assert job is not None

        with pytest.raises(JobLeaseLostError):
            repository.complete(job.id, worker_id="worker-2", now=now)

        completed = repository.complete(job.id, worker_id="worker-1", now=now)
        session.commit()
        assert completed.status == "succeeded"
        assert completed.locked_by is None


def test_owner_cannot_complete_after_lease_expiry(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = JobRepository(session)
        repository.enqueue(job_type="inspect", aggregate_id="note-1", now=now)
        session.commit()
        job = repository.claim("worker-1", now, timedelta(seconds=10))
        session.commit()
        assert job is not None

        with pytest.raises(JobLeaseLostError):
            repository.complete(job.id, worker_id="worker-1", now=now + timedelta(seconds=11))


def test_expired_final_attempt_becomes_terminal(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = JobRepository(session)
        job = repository.enqueue(job_type="publish", aggregate_id="note-1", max_attempts=1, now=now)
        session.commit()
        claimed = repository.claim("worker-1", now, timedelta(seconds=10))
        session.commit()
        assert claimed is not None

        assert (
            repository.claim("worker-2", now + timedelta(seconds=11), timedelta(seconds=10)) is None
        )
        session.commit()
        session.refresh(job)

        assert job.status == "failed"
        assert job.last_error == "lease expired after final attempt"


def test_failed_job_is_retried_then_becomes_terminal(engine: Engine) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        repository = JobRepository(session)
        repository.enqueue(job_type="publish", aggregate_id="note-1", max_attempts=2, now=now)
        session.commit()

        first = repository.claim("worker-1", now, timedelta(seconds=30))
        assert first is not None
        retried = repository.fail(
            first.id,
            worker_id="worker-1",
            error="Anki unavailable",
            retry_at=now + timedelta(seconds=5),
            now=now,
        )
        session.commit()
        assert retried.status == "pending"

        second = repository.claim("worker-2", now + timedelta(seconds=5), timedelta(seconds=30))
        assert second is not None
        terminal = repository.fail(
            second.id,
            worker_id="worker-2",
            error="Anki unavailable",
            retry_at=now + timedelta(seconds=10),
            now=now + timedelta(seconds=5),
        )
        session.commit()

        assert terminal.status == "failed"
        assert terminal.last_error == "Anki unavailable"
