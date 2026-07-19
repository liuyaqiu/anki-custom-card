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

DICTIONARY_INSTRUCTIONS = """You are a synthetic dictionary provider for an advanced English
learner. Return lexical evidence only, following the supplied schema. Cover useful senses,
part of speech, IPA when confident, concise English definitions, optional short Chinese glosses,
professional examples, collocations, register, and domain. Prefer workplace and IT relevance
without distorting meaning. Sense IDs must be stable descriptive identifiers. This is synthetic
dictionary output, not an authoritative citation. Do not return HTML."""

CARD_INSTRUCTIONS = """Compose one advanced-English Anki note from the explicit dictionary JSON.
Select coherent source senses and preserve their IDs. English definition and natural example are
primary; keep Chinese concise. Prefer workplace and IT contexts when semantically appropriate.
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
    prompt_version = "dictionary-v1"
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
    prompt_version = "card-v1"

    def __init__(self, *, client: Any, model: str = "gpt-5.6-luna") -> None:
        self.client = client
        self.model = model

    async def compose(
        self, dictionary_output: DictionaryOutput, *, word_idx: int, domain: str
    ) -> GeneratedOutput[CardDraft]:
        explicit_input = json.dumps(
            {
                "dictionary_output": dictionary_output.model_dump(mode="json", by_alias=True),
                "card_request": {"word_idx": word_idx, "preferred_domain": domain},
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
