# ruff: noqa: RUF001

import pytest
from pydantic import ValidationError

from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput

pytestmark = pytest.mark.unit


def dictionary_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "query": {"word": "deployment", "normalized_word": "deployment", "language": "en"},
        "entries": [
            {
                "part_of_speech": "noun",
                "ipa": "/dɪˈplɔɪmənt/",
                "register": "neutral",
                "domains": ["information technology"],
                "senses": [
                    {
                        "sense_id": "noun.it.release",
                        "definition_en": "The process of making software available for use.",
                        "definition_zh": "部署；将软件投入使用",
                        "examples": [
                            {
                                "text": "The team postponed the deployment.",
                                "domain": "information technology",
                                "register": "professional",
                            }
                        ],
                        "collocations": ["production deployment"],
                    }
                ],
            }
        ],
        "warnings": [],
    }


def test_dictionary_output_accepts_structured_lexical_evidence() -> None:
    output = DictionaryOutput.model_validate(dictionary_payload())

    assert output.query.normalized_word == "deployment"
    assert output.entries[0].senses[0].sense_id == "noun.it.release"


def test_dictionary_output_rejects_duplicate_sense_ids() -> None:
    payload = dictionary_payload()
    entry = payload["entries"][0]  # type: ignore[index]
    entry["senses"].append(entry["senses"][0])  # type: ignore[index,union-attr]

    with pytest.raises(ValidationError, match="sense_id"):
        DictionaryOutput.model_validate(payload)


def test_card_draft_rejects_html_and_invalid_word_idx() -> None:
    payload = {
        "schema_version": 1,
        "word": "deployment",
        "word_idx": -1,
        "selected_sense_ids": ["noun.it.release"],
        "fields": {
            "word": "deployment",
            "part_of_speech": "noun",
            "ipa": "/dɪˈplɔɪmənt/",
            "definition_en": "<b>Software release.</b>",
            "definition_zh": "部署",
            "example": "We automated the deployment.",
            "example_zh": "我们实现了部署自动化。",
            "collocations": ["automated deployment"],
            "usage_note": "Common in software engineering.",
        },
        "speech": {
            "word_text": "deployment",
            "example_text": "We automated the deployment.",
        },
    }

    with pytest.raises(ValidationError) as error:
        CardDraft.model_validate(payload)

    messages = str(error.value)
    assert "word_idx" in messages
    assert "HTML" in messages


def test_card_draft_is_plain_data_for_server_side_rendering() -> None:
    payload = {
        "schema_version": 1,
        "word": "deployment",
        "word_idx": 0,
        "selected_sense_ids": ["noun.it.release"],
        "fields": {
            "word": "deployment",
            "part_of_speech": "noun",
            "ipa": "/dɪˈplɔɪmənt/",
            "definition_en": "The process of making software available for use.",
            "definition_zh": "部署",
            "example": "We automated the deployment.",
            "example_zh": "我们实现了部署自动化。",
            "collocations": ["automated deployment"],
            "usage_note": "Common in software engineering.",
        },
        "speech": {
            "word_text": "deployment",
            "example_text": "We automated the deployment.",
        },
    }

    draft = CardDraft.model_validate(payload)

    assert draft.word_idx == 0
    assert draft.fields.definition_zh == "部署"
