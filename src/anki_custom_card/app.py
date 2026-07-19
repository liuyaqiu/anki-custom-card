from fastapi import FastAPI

from anki_custom_card import __version__
from anki_custom_card.api.health import router as health_router
from anki_custom_card.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    application = FastAPI(title="Anki Custom Card", version=__version__)
    application.state.settings = resolved_settings
    application.include_router(health_router)
    return application


app = create_app()
