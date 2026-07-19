import base64

import httpx
import pytest

from anki_custom_card.integrations.anki_connect.client import (
    AnkiConnectClient,
    AnkiConnectError,
)

pytestmark = pytest.mark.unit


@pytest.mark.anyio
async def test_client_uses_v6_envelope_and_base64_media() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload == {
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "acc.mp3", "data": base64.b64encode(b"audio").decode()},
        }
        return httpx.Response(200, json={"result": "acc.mp3", "error": None})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnkiConnectClient("http://127.0.0.1:8765", client=http_client)
    assert await client.store_media(filename="acc.mp3", content=b"audio") == "acc.mp3"
    await http_client.aclose()


@pytest.mark.anyio
async def test_client_rejects_anki_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": None, "error": "bad model"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnkiConnectClient("http://127.0.0.1:8765", client=http_client)
    with pytest.raises(AnkiConnectError) as error:
        await client.model_names()
    assert error.value.code == "anki_action_failed"
    assert error.value.retryable is False
    await http_client.aclose()


@pytest.mark.anyio
async def test_notes_info_ignores_anki_placeholders_for_missing_notes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload == {
            "action": "notesInfo",
            "version": 6,
            "params": {"notes": [41, 42]},
        }
        return httpx.Response(
            200,
            json={
                "result": [
                    {},
                    {"noteId": 42, "fields": {"Word": {"value": "dilute"}}},
                ],
                "error": None,
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnkiConnectClient("http://127.0.0.1:8765", client=http_client)

    assert await client.notes_info([41, 42]) == [
        {"noteId": 42, "fields": {"Word": {"value": "dilute"}}}
    ]
    await http_client.aclose()
