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

    @model_validator(mode="after")
    def require_loopback_host(self) -> Self:
        try:
            is_loopback = ip_address(self.host).is_loopback
        except ValueError:
            is_loopback = self.host == "localhost"

        if not is_loopback:
            raise ValueError("host must resolve to a loopback address in local mode")
        return self
