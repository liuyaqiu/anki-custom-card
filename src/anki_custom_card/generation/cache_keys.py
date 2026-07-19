import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class DictionaryCacheIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    provider_dataset: str | None = None
    normalized_query: dict[str, object]
    provider_config_version: str = Field(min_length=1)
    prompt_version: str | None = None
    schema_version: int = Field(ge=1)
    model: str | None = None

    @property
    def request_key(self) -> str:
        canonical = json.dumps(
            self.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
