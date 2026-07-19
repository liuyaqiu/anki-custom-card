import pytest
from fastapi.testclient import TestClient

from anki_custom_card.app import create_app
from anki_custom_card.config import Settings
from anki_custom_card.integrations.anki_connect.client import AnkiConnectError

pytestmark = pytest.mark.unit


def test_health_endpoint_reports_service_status() -> None:
    app = create_app(Settings())

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "anki-custom-card",
        "status": "ok",
        "version": "0.1.0",
    }


def test_anki_health_reports_version_without_exposing_configuration(monkeypatch) -> None:
    class FakeClient:
        async def version(self) -> int:
            return 6

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        "anki_custom_card.api.health.build_anki_connect_client", lambda settings: FakeClient()
    )
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/health/anki")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": 6, "error_code": None}


def test_anki_health_reports_stable_unavailable_error(monkeypatch) -> None:
    class OfflineClient:
        async def version(self) -> int:
            raise AnkiConnectError("anki_unavailable", "connection refused", retryable=True)

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        "anki_custom_card.api.health.build_anki_connect_client", lambda settings: OfflineClient()
    )
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/health/anki")
    assert response.json() == {
        "status": "unavailable",
        "version": None,
        "error_code": "anki_unavailable",
    }
