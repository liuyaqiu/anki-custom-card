from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from anki_custom_card.generation.pipeline import GenerationPipeline
from anki_custom_card.generation.ports import GeneratedOutput
from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput, DictionaryQuery
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.generation_repository import GenerationRepository
from anki_custom_card.persistence.models import Artifact, Base, Draft, GenerationJob

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = build_engine(f"sqlite:///{tmp_path / 'generation.db'}")
    Base.metadata.create_all(value)
    yield value
    value.dispose()


def dictionary_output() -> DictionaryOutput:
    return DictionaryOutput.model_validate(
        {
            "schema_version": 1,
            "query": {"word": "deployment", "normalized_word": "deployment", "language": "en"},
            "entries": [
                {
                    "part_of_speech": "noun",
                    "senses": [
                        {
                            "sense_id": "noun.it.release",
                            "definition_en": "The process of making software available for use.",
                        }
                    ],
                }
            ],
        }
    )


def card_draft() -> CardDraft:
    return CardDraft.model_validate(
        {
            "schema_version": 1,
            "word": "deployment",
            "word_idx": 0,
            "selected_sense_ids": ["noun.it.release"],
            "fields": {
                "word": "deployment",
                "part_of_speech": "noun",
                "definition_en": "The process of making software available for use.",
                "definition_zh": "部署",
                "example": "We automated the deployment.",
                "example_zh": "我们实现了部署自动化。",
            },
            "speech": {
                "word_text": "deployment",
                "example_text": "We automated the deployment.",
            },
        }
    )


class FakeDictionaryProvider:
    provider_name = "openai"
    provider_dataset = "synthetic_dictionary"
    provider_config_version = "1"
    prompt_version = "dictionary-v1"
    schema_version = 1
    model = "gpt-5.6-luna"

    def __init__(self) -> None:
        self.calls = 0

    async def lookup(self, query: DictionaryQuery) -> GeneratedOutput[DictionaryOutput]:
        self.calls += 1
        return GeneratedOutput(
            content=dictionary_output(),
            response_id="dict-response",
            model=self.model,
            raw_response="dictionary raw response",
        )


class FlakyCardComposer:
    provider_name = "openai"
    prompt_version = "card-v1"
    model = "gpt-5.6-luna"

    def __init__(self) -> None:
        self.calls = 0

    async def compose(
        self, output: DictionaryOutput, *, word_idx: int, domain: str
    ) -> GeneratedOutput[CardDraft]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary composer failure")
        return GeneratedOutput(
            content=card_draft(),
            response_id="card-response",
            model=self.model,
            raw_response="card raw response",
        )


class FailingDictionaryProvider(FakeDictionaryProvider):
    async def lookup(self, query: DictionaryQuery) -> GeneratedOutput[DictionaryOutput]:
        self.calls += 1
        raise RuntimeError("dictionary unavailable")


@pytest.mark.anyio
async def test_retry_resumes_from_persisted_dictionary_artifact(engine: Engine) -> None:
    sessions = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 19, 11, 0, tzinfo=UTC)
    with sessions() as session:
        job = GenerationRepository(session).create_job("deployment", "en", now=now)
        session.commit()

    dictionary = FakeDictionaryProvider()
    composer = FlakyCardComposer()
    pipeline = GenerationPipeline(sessions, dictionary, composer)

    with pytest.raises(RuntimeError, match="temporary composer failure"):
        await pipeline.run(job.id, word_idx=0, domain="it", now=now)

    draft = await pipeline.run(job.id, word_idx=0, domain="it", now=now)

    assert dictionary.calls == 1
    assert composer.calls == 2
    assert draft.word == "deployment"
    with sessions() as session:
        stored_job = session.get(GenerationJob, job.id)
        assert stored_job is not None and stored_job.status == "succeeded"
        assert session.scalar(select(func.count()).select_from(Artifact)) == 2
        assert session.scalar(select(func.count()).select_from(Draft)) == 1

    same_draft = await pipeline.run(job.id, word_idx=0, domain="it", now=now)
    assert same_draft == draft
    assert composer.calls == 2


@pytest.mark.anyio
async def test_dictionary_failure_marks_generation_job_failed(engine: Engine) -> None:
    sessions = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 19, 11, 0, tzinfo=UTC)
    with sessions() as session:
        job = GenerationRepository(session).create_job("deployment", "en", now=now)
        session.commit()

    pipeline = GenerationPipeline(sessions, FailingDictionaryProvider(), FlakyCardComposer())
    with pytest.raises(RuntimeError, match="dictionary unavailable"):
        await pipeline.run(job.id, word_idx=0, domain="it", now=now)

    with sessions() as session:
        stored_job = session.get(GenerationJob, job.id)
        assert stored_job is not None
        assert stored_job.status == "failed"
        assert stored_job.error_code == "generation_failed"
