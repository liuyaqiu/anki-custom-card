from ipaddress import ip_address
from pathlib import Path
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from ACC_-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ACC_",
        extra="ignore",
    )

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/app.db"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = 60.0
    azure_speech_key: SecretStr | None = None
    azure_speech_region: str | None = None
    azure_speech_locale: str = "en-US"
    azure_speech_voice: str = "en-US-AvaMultilingualNeural"
    azure_speech_output_format: str = "audio-24khz-96kbitrate-mono-mp3"
    azure_speech_rate: str = "-8%"
    azure_speech_config_version: str = "1"
    anki_connect_url: str = "http://127.0.0.1:8765"
    anki_connect_timeout_seconds: float = 10.0
    anki_deck: str = "Anki Custom Card"
    worker_enabled: bool = True
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 120

    @model_validator(mode="after")
    def require_local_host(self) -> Self:
        try:
            address = ip_address(self.host)
            is_local = (address.is_loopback or address.is_private) and not (
                address.is_unspecified or address.is_multicast or address.is_link_local
            )
        except ValueError:
            is_local = self.host == "localhost"

        if not is_local:
            raise ValueError("host must be a loopback or explicit private LAN address")
        if self.azure_speech_locale != "en-US" or not self.azure_speech_voice.startswith("en-US-"):
            raise ValueError("Azure Speech must use an en-US locale and voice")
        return self
