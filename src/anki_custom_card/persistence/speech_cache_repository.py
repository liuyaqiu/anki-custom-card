import hashlib
import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from anki_custom_card.persistence.models import SpeechCacheEntry, new_id


def speech_cache_key(
    *,
    provider: str,
    config_version: str,
    text: str,
    locale: str,
    voice: str,
    ssml: str,
    output_format: str,
) -> str:
    canonical = json.dumps(
        {
            "provider": provider,
            "config_version": config_version,
            "text": text,
            "locale": locale,
            "voice": voice,
            "ssml": ssml,
            "output_format": output_format,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class SpeechCacheRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, cache_key: str) -> SpeechCacheEntry | None:
        return self.session.scalar(
            select(SpeechCacheEntry).where(SpeechCacheEntry.cache_key == cache_key)
        )

    def put(self, *, cache_key: str, values: dict[str, object]) -> SpeechCacheEntry:
        self.session.execute(
            sqlite_insert(SpeechCacheEntry)
            .values(id=new_id(), cache_key=cache_key, **values)
            .on_conflict_do_nothing(index_elements=[SpeechCacheEntry.cache_key])
        )
        entry = self.get(cache_key)
        if entry is None:  # pragma: no cover
            raise RuntimeError(f"Failed to persist speech cache {cache_key}")
        return entry
