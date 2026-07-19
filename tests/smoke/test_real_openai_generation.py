import os

import pytest

from anki_custom_card.config import Settings
from anki_custom_card.generation.schemas import DictionaryQuery
from anki_custom_card.integrations.ai.factory import build_openai_generation

pytestmark = pytest.mark.smoke


@pytest.mark.anyio
async def test_real_openai_two_stage_generation() -> None:
    if os.getenv("ACC_RUN_OPENAI_SMOKE") != "1":
        pytest.skip("set ACC_RUN_OPENAI_SMOKE=1 to permit a billed OpenAI smoke test")

    dictionary, composer = build_openai_generation(Settings())
    dictionary_result = await dictionary.lookup(
        DictionaryQuery(word="deployment", normalized_word="deployment", language="en")
    )
    card_result = await composer.compose(dictionary_result.content, word_idx=0, domain="it")

    assert card_result.content.word == "deployment"
    assert card_result.content.selected_sense_ids
