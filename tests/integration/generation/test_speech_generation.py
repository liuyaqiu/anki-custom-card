from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from anki_custom_card.generation.speech import SpeechGenerationService
from anki_custom_card.integrations.tts.azure_speech import SpeechResult
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.generation_repository import GenerationRepository
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import (
    Artifact,
    Base,
    Media,
    SpeechCacheEntry,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = build_engine(f"sqlite:///{tmp_path / 'speech.db'}")
    Base.metadata.create_all(value)
    yield value
    value.dispose()


class FakeSpeechClient:
    provider_name = "azure_speech"
    config_version = "1"
    locale = "en-US"
    voice = "en-US-AvaMultilingualNeural"
    output_format = "audio-24khz-96kbitrate-mono-mp3"

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str) -> SpeechResult:
        self.calls += 1
        return SpeechResult(
            content=f"audio:{text}".encode(),
            mime_type="audio/mpeg",
            ssml=f"<speak>{text}</speak>",
        )

    def render_ssml(self, text: str) -> str:
        return f"<speak>{text}</speak>"


@pytest.mark.anyio
async def test_speech_is_cached_and_each_job_gets_artifact(engine: Engine, tmp_path: Path) -> None:
    sessions = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    with sessions() as session:
        first = GenerationRepository(session).create_job("deploy", "en", now=now)
        second = GenerationRepository(session).create_job("deploy", "en", now=now)
        session.commit()

    client = FakeSpeechClient()
    service = SpeechGenerationService(
        sessions, ContentAddressedMediaStore(tmp_path / "media"), client
    )
    await service.generate(first.id, "word_audio", "deploy", now=now)
    await service.generate(second.id, "word_audio", "deploy", now=now)

    assert client.calls == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Media)) == 1
        assert session.scalar(select(func.count()).select_from(SpeechCacheEntry)) == 1
        assert session.scalar(select(func.count()).select_from(Artifact)) == 2
        assert (
            MediaRepository(
                session, ContentAddressedMediaStore(tmp_path / "media")
            ).delete_unreferenced()
            == []
        )
