from unittest.mock import patch

import pytest

from anki_custom_card.config import Settings
from anki_custom_card.integrations.ai.factory import (
    OpenAIConfigurationError,
    build_openai_generation,
)

pytestmark = pytest.mark.unit


def test_factory_requires_api_key_only_when_openai_is_used() -> None:
    with pytest.raises(OpenAIConfigurationError, match="ACC_OPENAI_API_KEY"):
        build_openai_generation(Settings(_env_file=None))


def test_factory_shares_configured_client_between_both_stages() -> None:
    settings = Settings(openai_api_key="sk-test", openai_model="gpt-5.6-luna")
    with patch("anki_custom_card.integrations.ai.factory.AsyncOpenAI") as client_type:
        dictionary, composer = build_openai_generation(settings)

    client_type.assert_called_once_with(api_key="sk-test", timeout=60.0)
    assert dictionary.client is composer.client
    assert dictionary.model == composer.model == "gpt-5.6-luna"
