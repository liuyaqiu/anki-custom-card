from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.config import Settings
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Base, GenerationJob, Job
from anki_custom_card.services import ApplicationServices, PersistentWorker

pytestmark = pytest.mark.integration


class GenerationStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    async def run(self, generation_id, *, word_idx, domain, now):
        self.calls.append((generation_id, word_idx, domain))


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
