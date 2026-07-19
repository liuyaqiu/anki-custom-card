from pathlib import Path

import pytest
from pydantic import ValidationError

from anki_custom_card.config import Settings

pytestmark = pytest.mark.unit


def test_settings_use_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "ACC_ENVIRONMENT",
        "ACC_HOST",
        "ACC_PORT",
        "ACC_DATA_DIR",
        "ACC_DATABASE_URL",
        "ACC_OPENAI_API_KEY",
        "ACC_OPENAI_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.data_dir == Path("data")
    assert settings.database_url == "sqlite:///data/app.db"
    assert settings.openai_api_key is None
    assert settings.openai_model == "gpt-5.6-luna"


def test_openai_api_key_is_secret() -> None:
    settings = Settings(openai_api_key="sk-example-secret")

    assert "sk-example-secret" not in repr(settings)
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-example-secret"


def test_settings_allow_explicit_private_lan_host() -> None:
    assert Settings(host="192.168.88.9").host == "192.168.88.9"


@pytest.mark.parametrize("host", ["0.0.0.0", "8.8.8.8", "example.com"])
def test_settings_reject_unsafe_host(host: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        Settings(host=host)


def test_settings_reject_non_american_speech_voice() -> None:
    with pytest.raises(ValidationError, match="en-US"):
        Settings(azure_speech_locale="en-GB", azure_speech_voice="en-GB-SoniaNeural")
