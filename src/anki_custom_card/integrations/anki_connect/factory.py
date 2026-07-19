from anki_custom_card.config import Settings
from anki_custom_card.integrations.anki_connect.client import AnkiConnectClient


def build_anki_connect_client(settings: Settings) -> AnkiConnectClient:
    return AnkiConnectClient(
        settings.anki_connect_url, timeout=settings.anki_connect_timeout_seconds
    )
