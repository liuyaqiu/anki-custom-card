import os

import pytest

from anki_custom_card.config import Settings
from anki_custom_card.integrations.tts.factory import build_azure_speech

pytestmark = pytest.mark.smoke


@pytest.mark.anyio
async def test_real_azure_speech_returns_mp3() -> None:
    if os.getenv("ACC_RUN_AZURE_SPEECH_SMOKE") != "1":
        pytest.skip("set ACC_RUN_AZURE_SPEECH_SMOKE=1 to permit a billed Azure smoke test")

    client = build_azure_speech(Settings())
    try:
        result = await client.synthesize("deployment")
    finally:
        await client.http_client.aclose()

    assert result.content
    assert result.mime_type == "audio/mpeg"
