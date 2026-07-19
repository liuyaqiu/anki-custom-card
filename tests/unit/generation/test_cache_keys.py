import pytest

from anki_custom_card.generation.cache_keys import DictionaryCacheIdentity

pytestmark = pytest.mark.unit


def test_dictionary_cache_key_is_stable_and_versioned() -> None:
    first = DictionaryCacheIdentity(
        provider="openai",
        provider_dataset="synthetic_dictionary",
        normalized_query={"language": "en", "normalized_word": "deployment"},
        provider_config_version="1",
        prompt_version="dictionary-v1",
        schema_version=1,
        model="gpt-5.6-luna",
    )
    reordered = DictionaryCacheIdentity(
        provider="openai",
        provider_dataset="synthetic_dictionary",
        normalized_query={"normalized_word": "deployment", "language": "en"},
        provider_config_version="1",
        prompt_version="dictionary-v1",
        schema_version=1,
        model="gpt-5.6-luna",
    )

    assert first.request_key == reordered.request_key
    assert len(first.request_key) == 64

    changed_prompt = first.model_copy(update={"prompt_version": "dictionary-v2"})
    assert changed_prompt.request_key != first.request_key
