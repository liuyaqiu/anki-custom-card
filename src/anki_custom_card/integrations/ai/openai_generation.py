# ruff: noqa: E501 - prompt prose is kept readable as model-facing text
import json
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)

from anki_custom_card.generation.ports import GeneratedOutput
from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput, DictionaryQuery

DICTIONARY_INSTRUCTIONS = """You are a synthetic American English dictionary provider for an advanced English
learner. Return lexical evidence only, following the supplied schema. Cover useful senses,
part of speech, IPA when confident, concise English definitions, optional short Chinese glosses,
professional examples, collocations, register, and domain. Use General American IPA, American
spelling, vocabulary, grammar, and natural US usage only. Rank useful workplace and IT senses and
examples first when they are genuine, while still covering important general senses. Never force
an IT context onto an unrelated meaning. Sense IDs must be stable descriptive identifiers. This is synthetic
dictionary output, not an authoritative citation. Do not return HTML."""

CARD_INSTRUCTIONS = """Compose one advanced-American-English Anki note from the explicit dictionary JSON.
The zero-based candidate_index identifies a distinct meaning or practical usage scenario: do not
repeat the meaning selected by lower candidate indexes. Select one coherent sense cluster and
preserve its IDs. Classify it as general, workplace, or it in fields.domain. English definition and
natural example are primary; keep Chinese concise. Prefer genuine workplace and IT contexts first,
but include general contexts when they are more important or natural. Use General American IPA,
American spelling and idiomatic US examples exclusively. The speech texts must match that usage.
Return plain field data only: never return HTML, CSS, Anki markup, or audio binary data."""


class StructuredOutputError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


async def parse_response(parse_call: Any) -> Any:
    try:
        return await parse_call
    except (APIConnectionError, APITimeoutError, RateLimitError) as error:
        raise StructuredOutputError("openai_transient_error", str(error), retryable=True) from error
    except (AuthenticationError, PermissionDeniedError, BadRequestError) as error:
        raise StructuredOutputError(
            "openai_request_rejected", str(error), retryable=False
        ) from error


def raw_response(response: object) -> str:
    dump = getattr(response, "model_dump_json", None)
    if callable(dump):
        return str(dump(warnings=False))
    return json.dumps(
        {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", None),
            "output_text": getattr(response, "output_text", None),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


class OpenAIDictionaryProvider:
    provider_name = "openai"
    provider_dataset = "synthetic_dictionary"
    provider_config_version = "1"
    prompt_version = "dictionary-v2-american"
    schema_version = 1

    def __init__(self, *, client: Any, model: str = "gpt-5.6-luna") -> None:
        self.client = client
        self.model = model

    async def lookup(self, query: DictionaryQuery) -> GeneratedOutput[DictionaryOutput]:
        response = await parse_response(
            self.client.responses.parse(
                model=self.model,
                instructions=DICTIONARY_INSTRUCTIONS,
                input=query.model_dump_json(),
                text_format=DictionaryOutput,
                reasoning={"effort": "low"},
                previous_response_id=None,
                store=False,
            )
        )
        parsed = response.output_parsed
        if parsed is None:
            raise StructuredOutputError(
                "openai_missing_structured_output",
                "OpenAI response did not contain parsed dictionary output",
                retryable=True,
            )
        return GeneratedOutput(
            content=parsed,
            response_id=response.id,
            model=response.model,
            raw_response=raw_response(response),
        )


class OpenAICardComposer:
    provider_name = "openai"
    prompt_version = "card-v2-american-multisense"

    def __init__(self, *, client: Any, model: str = "gpt-5.6-luna") -> None:
        self.client = client
        self.model = model

    async def compose(
        self, dictionary_output: DictionaryOutput, *, word_idx: int, domain: str
    ) -> GeneratedOutput[CardDraft]:
        explicit_input = json.dumps(
            {
                "dictionary_output": dictionary_output.model_dump(mode="json", by_alias=True),
                "card_request": {
                    "word_idx": word_idx,
                    "candidate_index": word_idx,
                    "content_priority": ["information technology", "workplace", "general"],
                    "english_variant": "en-US",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        response = await parse_response(
            self.client.responses.parse(
                model=self.model,
                instructions=CARD_INSTRUCTIONS,
                input=explicit_input,
                text_format=CardDraft,
                reasoning={"effort": "low"},
                previous_response_id=None,
                store=False,
            )
        )
        parsed = response.output_parsed
        if parsed is None:
            raise StructuredOutputError(
                "openai_missing_structured_output",
                "OpenAI response did not contain parsed card output",
                retryable=True,
            )
        return GeneratedOutput(
            content=parsed,
            response_id=response.id,
            model=response.model,
            raw_response=raw_response(response),
        )
