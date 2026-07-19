import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

RATE_PATTERN = re.compile(r"^[+-]?\d{1,3}%$")


@dataclass(frozen=True)
class SpeechConfig:
    region: str
    key: str
    locale: str = "en-US"
    voice: str = "en-US-AvaMultilingualNeural"
    output_format: str = "audio-24khz-96kbitrate-mono-mp3"
    rate: str = "-8%"
    config_version: str = "1"


@dataclass(frozen=True)
class SpeechResult:
    content: bytes
    mime_type: str
    ssml: str


class AzureSpeechError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = "azure_speech_transient" if retryable else "azure_speech_rejected"


def build_ssml(text: str, config: SpeechConfig) -> str:
    if not text.strip():
        raise ValueError("speech text must not be blank")
    if not RATE_PATTERN.fullmatch(config.rate):
        raise ValueError("speech rate must be a percentage")
    speak = ET.Element(
        "speak",
        {"version": "1.0", "xmlns": "http://www.w3.org/2001/10/synthesis"},
    )
    speak.set("{http://www.w3.org/XML/1998/namespace}lang", config.locale)
    voice = ET.SubElement(speak, "voice", {"name": config.voice})
    prosody = ET.SubElement(voice, "prosody", {"rate": config.rate})
    prosody.text = text.strip()
    return ET.tostring(speak, encoding="unicode")


class AzureSpeechClient:
    provider_name = "azure_speech"

    def __init__(self, *, http_client: httpx.AsyncClient, config: SpeechConfig) -> None:
        self.http_client = http_client
        self.config = config
        self.config_version = config.config_version
        self.locale = config.locale
        self.voice = config.voice
        self.output_format = config.output_format

    async def synthesize(self, text: str) -> SpeechResult:
        ssml = self.render_ssml(text)
        try:
            response = await self.http_client.post(
                f"https://{self.config.region}.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={
                    "Ocp-Apim-Subscription-Key": self.config.key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": self.config.output_format,
                    "User-Agent": "anki-custom-card",
                },
                content=ssml.encode(),
            )
        except httpx.RequestError as error:
            raise AzureSpeechError(str(error), retryable=True) from error
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise AzureSpeechError(
                f"Azure Speech returned HTTP {response.status_code}", retryable=retryable
            )
        if not response.content:
            raise AzureSpeechError("Azure Speech returned empty audio", retryable=True)
        return SpeechResult(content=response.content, mime_type="audio/mpeg", ssml=ssml)

    def render_ssml(self, text: str) -> str:
        return build_ssml(text, self.config)
