from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from anki_custom_card import __version__
from anki_custom_card.integrations.anki_connect.client import AnkiConnectError
from anki_custom_card.integrations.anki_connect.factory import build_anki_connect_client

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    service: Literal["anki-custom-card"] = "anki-custom-card"
    status: Literal["ok"] = "ok"
    version: str = __version__


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


class AnkiHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    version: int | None = None
    error_code: str | None = None


@router.get("/health/anki", response_model=AnkiHealthResponse)
async def anki_health(request: Request) -> AnkiHealthResponse:
    client = build_anki_connect_client(request.app.state.settings)
    try:
        return AnkiHealthResponse(status="ok", version=await client.version())
    except AnkiConnectError as error:
        return AnkiHealthResponse(status="unavailable", error_code=error.code)
    finally:
        await client.close()
