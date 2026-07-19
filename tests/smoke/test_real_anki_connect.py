import os

import pytest

from anki_custom_card.config import Settings
from anki_custom_card.integrations.anki_connect.factory import build_anki_connect_client

pytestmark = pytest.mark.smoke


@pytest.mark.anyio
async def test_real_anki_connect_is_reachable() -> None:
    if os.getenv("ACC_RUN_ANKI_SMOKE") != "1":
        pytest.skip("set ACC_RUN_ANKI_SMOKE=1 to call local AnkiConnect")
    client = build_anki_connect_client(Settings())
    try:
        assert await client.version() >= 6
    finally:
        await client.close()
