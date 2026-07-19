import hashlib
import json
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from anki_custom_card.generation.cache_keys import DictionaryCacheIdentity
from anki_custom_card.persistence.models import DictionaryCacheEntry, new_id


class DictionaryCacheRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, request_key: str) -> DictionaryCacheEntry | None:
        return self.session.scalar(
            select(DictionaryCacheEntry).where(
                DictionaryCacheEntry.request_key == request_key,
                DictionaryCacheEntry.invalidated_at.is_(None),
            )
        )

    def put(
        self,
        identity: DictionaryCacheIdentity,
        response_payload: dict[str, object],
        *,
        source_entry_ids: list[str],
        now: datetime,
    ) -> DictionaryCacheEntry:
        canonical_response = json.dumps(
            response_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.session.execute(
            sqlite_insert(DictionaryCacheEntry)
            .values(
                id=new_id(),
                provider=identity.provider,
                provider_dataset=identity.provider_dataset,
                provider_config_version=identity.provider_config_version,
                prompt_version=identity.prompt_version,
                schema_version=identity.schema_version,
                model=identity.model,
                request_key=identity.request_key,
                normalized_query=identity.normalized_query,
                response_payload=response_payload,
                response_hash=hashlib.sha256(canonical_response.encode()).hexdigest(),
                source_entry_ids=source_entry_ids,
                fetched_at=now,
            )
            .on_conflict_do_nothing(index_elements=["provider", "request_key"])
        )
        entry = self.session.scalar(
            select(DictionaryCacheEntry).where(
                DictionaryCacheEntry.provider == identity.provider,
                DictionaryCacheEntry.request_key == identity.request_key,
            )
        )
        if entry is None:  # pragma: no cover - guarded by the insert/select transaction
            raise RuntimeError(f"Failed to persist dictionary cache {identity.request_key}")
        return entry

    def invalidate(self, entry_id: str, *, now: datetime) -> None:
        self.session.execute(
            update(DictionaryCacheEntry)
            .where(DictionaryCacheEntry.id == entry_id)
            .values(invalidated_at=now)
        )
