from unittest.mock import patch

import pytest

from anki_custom_card.config import Settings
from anki_custom_card.integrations.tts.factory import (
    AzureSpeechConfigurationError,
    build_azure_speech,
)

pytestmark = pytest.mark.unit


def test_factory_requires_key_and_region() -> None:
    with pytest.raises(AzureSpeechConfigurationError, match="ACC_AZURE_SPEECH_KEY"):
        build_azure_speech(Settings(_env_file=None))


def test_factory_builds_configured_client_without_exposing_secret() -> None:
    settings = Settings(
        _env_file=None,
        azure_speech_key="azure-secret",
        azure_speech_region="eastasia",
    )
    with patch("anki_custom_card.integrations.tts.factory.httpx.AsyncClient"):
        client = build_azure_speech(settings)

    assert client.config.region == "eastasia"
    assert client.config.key == "azure-secret"
    assert "azure-secret" not in repr(settings)
