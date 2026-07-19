import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from anki_custom_card.config import Settings
from anki_custom_card.deletion import NoteDeletionService
from anki_custom_card.generation.pipeline import GenerationPipeline
from anki_custom_card.generation.speech import SpeechGenerationService
from anki_custom_card.integrations.ai.factory import build_openai_generation
from anki_custom_card.integrations.anki_connect.factory import build_anki_connect_client
from anki_custom_card.integrations.tts.factory import build_azure_speech
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Job
from anki_custom_card.publishing.inspection import AnkiInspectionService
from anki_custom_card.publishing.jobs import PublicationJobHandler
from anki_custom_card.publishing.service import PublicationService


class ApplicationServices:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        data_dir = settings.data_dir.resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = build_engine(settings.database_url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.media_store = ContentAddressedMediaStore(data_dir / "media")
        self.note_deletion = NoteDeletionService(self.sessions, self.media_store)
        self.anki = build_anki_connect_client(settings)
        self.publication = PublicationService(
            self.sessions, self.anki, self.media_store, deck=settings.anki_deck
        )
        self.inspection = AnkiInspectionService(self.sessions, self.anki)
        self.publication_jobs = PublicationJobHandler(
            self.sessions, self.publication, self.inspection
        )
        self.generation: GenerationPipeline | None = None
        self.azure = None
        if settings.openai_api_key is not None:
            dictionary, composer = build_openai_generation(settings)
            speech = None
            if settings.azure_speech_key is not None and settings.azure_speech_region is not None:
                self.azure = build_azure_speech(settings)
                speech = SpeechGenerationService(self.sessions, self.media_store, self.azure)
            self.generation = GenerationPipeline(self.sessions, dictionary, composer, speech)
        self.worker = PersistentWorker(self)

    async def close(self) -> None:
        await self.worker.stop()
        await self.anki.close()
        if self.azure is not None:
            await self.azure.http_client.aclose()
        self.engine.dispose()


class PersistentWorker:
    def __init__(self, services: ApplicationServices) -> None:
        self.services = services
        self.worker_id = f"local-{uuid4()}"
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    def notify(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        with self.services.sessions.begin() as session:
            job = JobRepository(session).claim(
                self.worker_id,
                now,
                timedelta(seconds=self.services.settings.worker_lease_seconds),
            )
            if job is None:
                return False
            job_id = job.id
            job_type = job.job_type
            payload = dict(job.payload)
            aggregate_id = job.aggregate_id
        if job_type in {"publish", "delete_anki", "inspect"}:
            await self.services.publication_jobs.run(job_id, worker_id=self.worker_id)
            return True
        if job_type == "generate":
            await self._run_generation(job_id, aggregate_id, payload)
            return True
        await self._fail(job_id, ValueError(f"unsupported job type: {job_type}"), retryable=False)
        return True

    async def _run_generation(
        self, job_id: str, generation_id: str, payload: dict[str, object]
    ) -> None:
        if self.services.generation is None:
            await self._fail(
                job_id,
                RuntimeError("OpenAI generation is not configured"),
                retryable=False,
            )
            return
        try:
            await self.services.generation.run(
                generation_id,
                word_idx=int(payload.get("word_idx", 0)),
                domain="mixed",
                now=datetime.now(UTC),
            )
        except Exception as error:
            await self._fail(job_id, error, retryable=bool(getattr(error, "retryable", True)))
            return
        with self.services.sessions.begin() as session:
            JobRepository(session).complete(job_id, worker_id=self.worker_id, now=datetime.now(UTC))

    async def _fail(self, job_id: str, error: Exception, *, retryable: bool) -> None:
        now = datetime.now(UTC)
        with self.services.sessions.begin() as session:
            job = session.get(Job, job_id)
            attempt = job.attempts if job is not None else 1
            JobRepository(session).fail(
                job_id,
                worker_id=self.worker_id,
                error=str(error),
                retry_at=now + timedelta(seconds=min(300, 2 ** max(0, attempt - 1))),
                now=now,
                retryable=retryable,
            )

    async def _loop(self) -> None:
        while True:
            worked = await self.run_once()
            if worked:
                continue
            self._wake.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.services.settings.worker_poll_seconds
                )
