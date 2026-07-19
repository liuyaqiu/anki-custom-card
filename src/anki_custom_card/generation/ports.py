from dataclasses import dataclass
from typing import Protocol

from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput, DictionaryQuery


@dataclass(frozen=True)
class GeneratedOutput[OutputT]:
    content: OutputT
    response_id: str
    model: str
    raw_response: str


class DictionaryProvider(Protocol):
    provider_name: str
    provider_dataset: str
    provider_config_version: str
    prompt_version: str
    schema_version: int
    model: str

    async def lookup(self, query: DictionaryQuery) -> GeneratedOutput[DictionaryOutput]: ...


class CardComposer(Protocol):
    provider_name: str
    prompt_version: str
    model: str

    async def compose(
        self, dictionary_output: DictionaryOutput, *, word_idx: int, domain: str
    ) -> GeneratedOutput[CardDraft]: ...
