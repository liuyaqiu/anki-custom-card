from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import Artifact
from anki_custom_card.persistence.speech_cache_repository import (
    SpeechCacheRepository,
    speech_cache_key,
)


class SpeechGenerator(Protocol):
    async def generate(self, job_id: str, usage: str, text: str, *, now: datetime) -> str: ...


class SpeechGenerationService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        media_store: ContentAddressedMediaStore,
        client: Any,
    ) -> None:
        self.session_factory = session_factory
        self.media_store = media_store
        self.client = client

    async def generate(self, job_id: str, usage: str, text: str, *, now: datetime) -> str:
        ssml = self.client.render_ssml(text)
        key = speech_cache_key(
            provider=self.client.provider_name,
            config_version=self.client.config_version,
            text=text,
            locale=self.client.locale,
            voice=self.client.voice,
            ssml=ssml,
            output_format=self.client.output_format,
        )
        with self.session_factory() as session:
            existing = session.scalar(
                select(Artifact).where(
                    Artifact.generation_job_id == job_id, Artifact.artifact_type == usage
                )
            )
            if existing is not None and existing.media_id is not None:
                return existing.media_id
            cached = SpeechCacheRepository(session).get(key)
            if cached is not None:
                self._add_artifact(session, job_id, usage, cached.media_id, cached.ssml)
                session.commit()
                return cached.media_id

        result = await self.client.synthesize(text)
        with self.session_factory() as session:
            media = MediaRepository(session, self.media_store).add(
                content=result.content, media_type="audio", mime_type=result.mime_type
            )
            cached = SpeechCacheRepository(session).put(
                cache_key=key,
                values={
                    "provider": self.client.provider_name,
                    "config_version": self.client.config_version,
                    "text": text,
                    "locale": self.client.locale,
                    "voice": self.client.voice,
                    "ssml": result.ssml,
                    "output_format": self.client.output_format,
                    "media_id": media.id,
                },
            )
            self._add_artifact(session, job_id, usage, cached.media_id, cached.ssml)
            session.commit()
            return cached.media_id

    def _add_artifact(
        self, session: Session, job_id: str, usage: str, media_id: str, ssml: str
    ) -> None:
        session.add(
            Artifact(
                generation_job_id=job_id,
                artifact_type=usage,
                provider=self.client.provider_name,
                structured_content={"ssml": ssml},
                media_id=media_id,
            )
        )
