import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.config import Settings
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Base, GenerationJob, Job
from anki_custom_card.services import ApplicationServices, PersistentWorker, WorkerPool

pytestmark = pytest.mark.integration


class GenerationStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    async def run(self, generation_id, *, word_idx, domain, now):
        self.calls.append((generation_id, word_idx, domain))


class RetryableGenerationStub:
    def __init__(self, sessions) -> None:
        self.sessions = sessions

    async def run(self, generation_id, *, word_idx, domain, now):
        with self.sessions.begin() as session:
            session.get(GenerationJob, generation_id).status = "failed"  # type: ignore[union-attr]
        raise RuntimeError("temporary provider outage")


class ConcurrentGenerationStub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, generation_id, *, word_idx, domain, now):
        self.calls.append(generation_id)
        if len(self.calls) == 3:
            self.all_started.set()
        await self.release.wait()


class PublicationJobsStub:
    def __init__(self, sessions) -> None:
        self.sessions = sessions
        self.calls: list[str] = []

    async def run(self, job_id, *, worker_id):
        self.calls.append(job_id)
        with self.sessions.begin() as session:
            JobRepository(session).complete(job_id, worker_id=worker_id, now=datetime.now(UTC))


@pytest.mark.anyio
async def test_worker_runs_generation_and_delegates_publication(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    generation = GenerationStub()
    publishing = PublicationJobsStub(sessions)
    services = SimpleNamespace(
        settings=Settings(environment="test", worker_enabled=False),
        sessions=sessions,
        generation=generation,
        publication_jobs=publishing,
    )
    worker = PersistentWorker(services)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    with sessions.begin() as session:
        source = GenerationJob(input_word="deploy", language="en", provider_config={})
        session.add(source)
        session.flush()
        JobRepository(session).enqueue(
            job_type="generate",
            aggregate_id=source.id,
            payload={"word_idx": 2, "domain": "it"},
            now=now,
        )
    assert await worker.run_once() is True
    assert generation.calls == [(source.id, 2, "mixed")]
    with sessions.begin() as session:
        JobRepository(session).enqueue(job_type="inspect", aggregate_id="note-1", now=now)
    assert await worker.run_once() is True
    assert len(publishing.calls) == 1
    assert await worker.run_once() is False
    engine.dispose()


@pytest.mark.anyio
async def test_three_workers_run_distinct_jobs_concurrently(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'three-workers.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    generation = ConcurrentGenerationStub()
    services = SimpleNamespace(
        settings=Settings(environment="test", worker_count=3, worker_poll_seconds=0.01),
        sessions=sessions,
        generation=generation,
        publication_jobs=PublicationJobsStub(sessions),
    )
    pool = WorkerPool(services, 3)  # type: ignore[arg-type]
    with sessions.begin() as session:
        for word_idx in range(3):
            source = GenerationJob(input_word="drown", language="en")
            session.add(source)
            session.flush()
            JobRepository(session).enqueue(
                job_type="generate",
                aggregate_id=source.id,
                payload={"word_idx": word_idx},
                now=datetime.now(UTC),
            )

    pool.start()
    try:
        await asyncio.wait_for(generation.all_started.wait(), timeout=2)
        assert len(set(generation.calls)) == 3
        assert len({worker.worker_id for worker in pool.workers}) == 3
        generation.release.set()
        async with asyncio.timeout(2):
            while True:
                with sessions() as session:
                    jobs = session.query(Job).all()
                    if len(jobs) == 3 and all(job.status == "succeeded" for job in jobs):
                        break
                await asyncio.sleep(0.01)
    finally:
        generation.release.set()
        await pool.stop()
        engine.dispose()


@pytest.mark.anyio
async def test_worker_marks_unconfigured_generation_terminal(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'worker-failed.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    services = SimpleNamespace(
        settings=Settings(environment="test", worker_enabled=False),
        sessions=sessions,
        generation=None,
        publication_jobs=PublicationJobsStub(sessions),
    )
    worker = PersistentWorker(services)  # type: ignore[arg-type]
    with sessions.begin() as session:
        JobRepository(session).enqueue(
            job_type="generate", aggregate_id="generation-1", now=datetime.now(UTC)
        )
    assert await worker.run_once() is True
    with Session(engine) as session:
        job = session.query(Job).one()
        assert job.status == "failed"
        assert "not configured" in job.last_error
    engine.dispose()


@pytest.mark.anyio
async def test_retryable_generation_failure_remains_pending_for_polling(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'worker-retry.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    services = SimpleNamespace(
        settings=Settings(environment="test", worker_enabled=False),
        sessions=sessions,
        generation=RetryableGenerationStub(sessions),
        publication_jobs=PublicationJobsStub(sessions),
    )
    worker = PersistentWorker(services)  # type: ignore[arg-type]
    with sessions.begin() as session:
        generation = GenerationJob(input_word="drown", language="en", status="pending")
        session.add(generation)
        session.flush()
        generation_id = generation.id
        JobRepository(session).enqueue(
            job_type="generate", aggregate_id=generation_id, now=datetime.now(UTC)
        )

    assert await worker.run_once() is True
    with sessions() as session:
        job = session.query(Job).filter_by(aggregate_id=generation_id).one()
        assert job.status == "pending"
        assert job.last_error == "temporary provider outage"
        assert session.get(GenerationJob, generation_id).status == "pending"  # type: ignore[union-attr]
    engine.dispose()


@pytest.mark.anyio
async def test_worker_keeps_polling_after_unhandled_job_error(monkeypatch) -> None:
    worker = PersistentWorker(SimpleNamespace(settings=Settings(worker_poll_seconds=0.01)))  # type: ignore[arg-type]
    resumed = asyncio.Event()
    calls = 0

    async def run_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("unexpected job failure")
        resumed.set()
        return False

    monkeypatch.setattr(worker, "run_once", run_once)
    worker.start()
    try:
        await asyncio.wait_for(resumed.wait(), timeout=1)
    finally:
        await worker.stop()
    assert calls >= 2


@pytest.mark.anyio
async def test_application_services_builds_and_closes_without_provider_keys(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'services.db'}",
        worker_enabled=False,
        openai_api_key=None,
        azure_speech_key=None,
        azure_speech_region=None,
    )
    services = ApplicationServices(settings)
    Base.metadata.create_all(services.engine)
    assert services.generation is None
    await services.close()


@pytest.mark.anyio
async def test_application_services_builds_configured_provider_pipeline(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'configured-services.db'}",
        worker_enabled=False,
        openai_api_key="test-openai-key",
        azure_speech_key="test-azure-key",
        azure_speech_region="eastasia",
    )
    services = ApplicationServices(settings)
    Base.metadata.create_all(services.engine)
    assert services.generation is not None
    assert services.azure is not None
    await services.close()
