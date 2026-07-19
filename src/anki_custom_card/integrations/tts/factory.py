import httpx

from anki_custom_card.config import Settings
from anki_custom_card.integrations.tts.azure_speech import (
    AzureSpeechClient,
    SpeechConfig,
)


class AzureSpeechConfigurationError(RuntimeError):
    pass


def build_azure_speech(settings: Settings) -> AzureSpeechClient:
    if settings.azure_speech_key is None or settings.azure_speech_region is None:
        raise AzureSpeechConfigurationError(
            "ACC_AZURE_SPEECH_KEY and ACC_AZURE_SPEECH_REGION are required"
        )
    config = SpeechConfig(
        region=settings.azure_speech_region,
        key=settings.azure_speech_key.get_secret_value(),
        locale=settings.azure_speech_locale,
        voice=settings.azure_speech_voice,
        output_format=settings.azure_speech_output_format,
        rate=settings.azure_speech_rate,
        config_version=settings.azure_speech_config_version,
    )
    return AzureSpeechClient(http_client=httpx.AsyncClient(timeout=60.0), config=config)
