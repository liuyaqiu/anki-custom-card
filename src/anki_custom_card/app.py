from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from anki_custom_card import __version__
from anki_custom_card.api.health import router as health_router
from anki_custom_card.api.v1 import router as api_router
from anki_custom_card.config import Settings
from anki_custom_card.services import ApplicationServices


def create_app(
    settings: Settings | None = None,
    *,
    services: ApplicationServices | None = None,
    start_worker: bool | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    should_start_worker = (settings is None) if start_worker is None else start_worker

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        owned = services is None
        application.state.services = services or ApplicationServices(resolved_settings)
        if should_start_worker and resolved_settings.worker_enabled:
            application.state.services.worker.start()
        yield
        if owned:
            await application.state.services.close()

    application = FastAPI(title="Anki Custom Card", version=__version__, lifespan=lifespan)
    application.state.settings = resolved_settings

    @application.middleware("http")
    async def csrf_cookie(request: Request, call_next):
        token = request.cookies.get("acc_csrf") or token_urlsafe(32)
        request.state.csrf_token = token
        response = await call_next(request)
        if request.cookies.get("acc_csrf") is None:
            response.set_cookie("acc_csrf", token, secure=False, httponly=False, samesite="strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    package_directory = Path(__file__).resolve().parent
    packaged_spa = package_directory / "spa_dist"
    development_spa = package_directory.parents[1] / "frontend" / "dist"
    spa_directory = packaged_spa if packaged_spa.is_dir() else development_spa
    spa_assets = spa_directory / "assets"
    if spa_assets.is_dir():
        application.mount("/app/assets", StaticFiles(directory=spa_assets), name="spa-assets")

    @application.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse("/app/", status_code=307)

    @application.api_route(
        "/ui/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def retired_ui(path: str) -> RedirectResponse:
        return RedirectResponse("/app/", status_code=303)

    @application.get("/app", include_in_schema=False)
    def spa_redirect() -> RedirectResponse:
        return RedirectResponse("/app/")

    @application.get("/app/{path:path}", include_in_schema=False)
    def spa_entry(path: str) -> FileResponse:
        index = spa_directory / "index.html"
        if not index.is_file():
            raise RuntimeError("SPA assets are not built; run `make frontend-build`")
        return FileResponse(index)

    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
