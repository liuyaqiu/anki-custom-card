import httpx
import pytest

from anki_custom_card.integrations.tts.azure_speech import (
    AzureSpeechClient,
    AzureSpeechError,
    SpeechConfig,
    build_ssml,
)

pytestmark = pytest.mark.unit


def config() -> SpeechConfig:
    return SpeechConfig(
        region="eastasia",
        key="secret",
        locale="en-US",
        voice="en-US-AvaMultilingualNeural",
        output_format="audio-24khz-96kbitrate-mono-mp3",
        rate="-8%",
    )


def test_ssml_escapes_user_text() -> None:
    ssml = build_ssml("R&D < deployment", config())

    assert "R&amp;D &lt; deployment" in ssml
    assert '<prosody rate="-8%">' in ssml


@pytest.mark.anyio
async def test_client_sends_required_azure_headers_and_returns_mp3() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1"
        assert request.headers["Ocp-Apim-Subscription-Key"] == "secret"
        assert request.headers["Content-Type"] == "application/ssml+xml"
        assert request.headers["X-Microsoft-OutputFormat"] == config().output_format
        return httpx.Response(200, content=b"mp3-audio")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AzureSpeechClient(http_client=http_client, config=config())

    result = await client.synthesize("deployment")

    assert result.content == b"mp3-audio"
    assert result.mime_type == "audio/mpeg"
    await http_client.aclose()


@pytest.mark.anyio
async def test_client_classifies_retryable_server_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AzureSpeechClient(http_client=http_client, config=config())

    with pytest.raises(AzureSpeechError) as error:
        await client.synthesize("deployment")

    assert error.value.retryable is True
    await http_client.aclose()
