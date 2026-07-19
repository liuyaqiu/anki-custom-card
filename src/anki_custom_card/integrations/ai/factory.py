from openai import AsyncOpenAI

from anki_custom_card.config import Settings
from anki_custom_card.integrations.ai.openai_generation import (
    OpenAICardComposer,
    OpenAIDictionaryProvider,
)


class OpenAIConfigurationError(RuntimeError):
    pass


def build_openai_generation(
    settings: Settings,
) -> tuple[OpenAIDictionaryProvider, OpenAICardComposer]:
    if settings.openai_api_key is None:
        raise OpenAIConfigurationError("ACC_OPENAI_API_KEY is required for content generation")

    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.openai_timeout_seconds,
    )
    return (
        OpenAIDictionaryProvider(client=client, model=settings.openai_model),
        OpenAICardComposer(client=client, model=settings.openai_model),
    )
