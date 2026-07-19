from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from anki_custom_card import __version__

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    service: Literal["anki-custom-card"] = "anki-custom-card"
    status: Literal["ok"] = "ok"
    version: str = __version__


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
