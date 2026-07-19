from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from anki_custom_card.generation.ports import GeneratedOutput
from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput, DictionaryQuery
from anki_custom_card.integrations.ai.openai_generation import (
    OpenAICardComposer,
    OpenAIDictionaryProvider,
    StructuredOutputError,
    raw_response,
)

pytestmark = pytest.mark.unit


def dictionary_output() -> DictionaryOutput:
    return DictionaryOutput.model_validate(
        {
            "schema_version": 1,
            "query": {"word": "deployment", "normalized_word": "deployment", "language": "en"},
            "entries": [
                {
                    "part_of_speech": "noun",
                    "domains": ["information technology"],
                    "senses": [
                        {
                            "sense_id": "noun.it.release",
                            "definition_en": "The process of making software available for use.",
                            "definition_zh": "部署",
                            "examples": [{"text": "We automated the deployment."}],
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


def fake_client(parsed: object | None) -> tuple[SimpleNamespace, AsyncMock]:
    parse = AsyncMock(
        return_value=SimpleNamespace(
            id="resp_123",
            model="gpt-5.6-luna-2026-06-01",
            output_parsed=parsed,
            output_text="structured output",
        )
    )
    return SimpleNamespace(responses=SimpleNamespace(parse=parse)), parse


def test_raw_response_disables_sdk_generic_serializer_warnings() -> None:
    def dump_json(**kwargs: object) -> str:
        return str(kwargs)

    response = SimpleNamespace(model_dump_json=dump_json)

    serialized = raw_response(response)

    assert "'warnings': False" in serialized


@pytest.mark.anyio
async def test_dictionary_provider_uses_dictionary_schema_and_returns_trace() -> None:
    client, parse = fake_client(dictionary_output())
    provider = OpenAIDictionaryProvider(client=client, model="gpt-5.6-luna")

    result = await provider.lookup(
        DictionaryQuery(word="deployment", normalized_word="deployment", language="en")
    )

    assert isinstance(result, GeneratedOutput)
    assert result.content.entries[0].senses[0].sense_id == "noun.it.release"
    assert result.response_id == "resp_123"
    call = parse.await_args.kwargs
    assert call["text_format"] is DictionaryOutput
    assert call["previous_response_id"] is None
    assert "synthetic" in call["instructions"].lower()


@pytest.mark.anyio
async def test_card_composer_receives_explicit_dictionary_json() -> None:
    client, parse = fake_client(card_draft())
    composer = OpenAICardComposer(client=client, model="gpt-5.6-luna")

    result = await composer.compose(dictionary_output(), word_idx=0, domain="it")

    assert result.content.word_idx == 0
    call = parse.await_args.kwargs
    assert call["text_format"] is CardDraft
    assert '"sense_id":"noun.it.release"' in call["input"]
    assert call["previous_response_id"] is None


@pytest.mark.anyio
async def test_missing_parsed_output_is_classified() -> None:
    client, _ = fake_client(None)
    provider = OpenAIDictionaryProvider(client=client, model="gpt-5.6-luna")

    with pytest.raises(StructuredOutputError) as error:
        await provider.lookup(
            DictionaryQuery(word="deployment", normalized_word="deployment", language="en")
        )

    assert error.value.code == "openai_missing_structured_output"
    assert error.value.retryable is True


@pytest.mark.anyio
async def test_openai_connection_failure_is_classified_as_retryable() -> None:
    client, parse = fake_client(None)
    parse.side_effect = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    provider = OpenAIDictionaryProvider(client=client, model="gpt-5.6-luna")

    with pytest.raises(StructuredOutputError) as error:
        await provider.lookup(
            DictionaryQuery(word="deployment", normalized_word="deployment", language="en")
        )

    assert error.value.code == "openai_transient_error"
    assert error.value.retryable is True
