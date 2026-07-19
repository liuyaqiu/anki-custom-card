import pytest
from fastapi.testclient import TestClient

from anki_custom_card.app import create_app
from anki_custom_card.config import Settings

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
