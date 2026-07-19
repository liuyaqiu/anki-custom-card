import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from anki_custom_card.app import create_app
from anki_custom_card.config import Settings
from anki_custom_card.deletion import NoteDeletionService
from anki_custom_card.generation.schemas import CardDraft
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.models import Base, Draft, GenerationJob, Job
from anki_custom_card.publishing.note_type import CSS, FIELDS, FRONT_TEMPLATE

pytestmark = pytest.mark.integration


class WorkerStub:
    def __init__(self) -> None:
        self.notifications = 0

    def notify(self) -> None:
        self.notifications += 1


class AnkiTemplateStub:
    def __init__(self) -> None:
        self.templates = None
        self.css = None

    async def deck_names(self):
        return ["Anki Custom Card"]

    async def create_deck(self, name):
        return 1

    async def model_names(self):
        return ["Anki Custom Card Basic v1"]

    async def model_field_names(self, name):
        return FIELDS

    async def update_model_templates(self, name, templates):
        self.templates = templates

    async def update_model_styling(self, name, css):
        self.css = css


class ServicesStub:
    def __init__(self, engine: Engine, tmp_path: Path) -> None:
        self.settings = Settings(
            environment="test",
            data_dir=tmp_path,
            database_url=f"sqlite:///{tmp_path / 'web.db'}",
            worker_enabled=False,
        )
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        self.media_store = ContentAddressedMediaStore(tmp_path / "media")
        self.note_deletion = NoteDeletionService(self.sessions, self.media_store)
        self.worker = WorkerStub()
        self.anki = AnkiTemplateStub()


@pytest.fixture
def web_app(tmp_path: Path) -> Iterator[tuple[TestClient, ServicesStub]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'web.db'}")
    Base.metadata.create_all(engine)
    services = ServicesStub(engine, tmp_path)
    app = create_app(services.settings, services=services, start_worker=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        yield client, services
    engine.dispose()


def card() -> CardDraft:
    return CardDraft.model_validate(
        {
            "schema_version": 1,
            "word": "deployment",
            "word_idx": 0,
            "selected_sense_ids": ["sense-1"],
            "fields": {
                "word": "deployment",
                "part_of_speech": "noun",
                "definition_en": "The act of releasing software.",
                "definition_zh": "部署",
                "example": "The deployment completed.",
                "example_zh": "部署完成了。",
                "collocations": ["continuous deployment"],
            },
            "speech": {
                "word_text": "deployment",
                "example_text": "The deployment completed.",
            },
        }
    )


def csrf(client: TestClient) -> str:
    response = client.get("/app/")
    assert response.status_code == 200
    return client.cookies["acc_csrf"]


def create_draft(services: ServicesStub) -> str:
    with services.sessions.begin() as session:
        generation = GenerationJob(
            input_word="deployment", language="en", status="succeeded", provider_config={}
        )
        session.add(generation)
        session.flush()
        draft = Draft(generation_job_id=generation.id, content=card().model_dump(mode="json"))
        session.add(draft)
        session.flush()
        return draft.id


def test_spa_is_the_only_ui_and_supports_deep_links(web_app) -> None:
    client, _ = web_app
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == "/app/"
    retired = client.get("/ui/notes/old", follow_redirects=False)
    assert retired.status_code == 303 and retired.headers["location"] == "/app/"

    entry = client.get("/app/")
    assert '<div id="app"></div>' in entry.text
    asset_path = re.search(r'src="(/app/assets/[^"]+\.js)"', entry.text)
    assert asset_path is not None
    assert client.get(asset_path.group(1)).status_code == 200
    assert client.get("/app/drafts/example").status_code == 200
    assert client.get("/static/app.css").status_code == 404


def test_generation_is_idempotent_and_immediately_visible_in_words_api(web_app) -> None:
    client, services = web_app
    token = csrf(client)
    headers = {"X-CSRF-Token": token}
    assert client.post("/api/generations", json={"word": "deploy"}).status_code == 403
    first = client.post("/api/generations", json={"word": "deploy"}, headers=headers)
    second = client.post("/api/generations", json={"word": " DEPLOY "}, headers=headers)
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["generation_ids"] == second.json()["generation_ids"]
    generation_id = first.json()["generation_ids"][0]
    assert client.get(f"/api/generations/{generation_id}").json()["word_idx"] == 0

    words = client.get("/api/words").json()
    assert words[0]["normalized"] == "deploy"
    assert words[0]["notes"] == []
    assert len(words[0]["generations"]) == 3
    assert client.get("/api/words/DEPLOY").json()["normalized"] == "deploy"
    assert client.get("/api/words/missing").status_code == 404
    with services.sessions() as session:
        assert len(list(session.scalars(select(GenerationJob)))) == 3
        assert len(list(session.scalars(select(Job)))) == 3


def test_spa_apis_cover_draft_note_archive_and_permanent_delete(web_app) -> None:
    client, services = web_app
    token = csrf(client)
    headers = {"X-CSRF-Token": token}
    assert client.get("/api/drafts/missing").status_code == 404
    draft_id = create_draft(services)
    draft = client.get(f"/api/drafts/{draft_id}").json()
    draft["content"]["fields"]["example"] = "The deployment is complete."
    saved = client.patch(
        f"/api/drafts/{draft_id}?expected_version=1",
        json=draft["content"],
        headers=headers,
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    confirmed = client.post(
        f"/api/drafts/{draft_id}/confirm",
        json={"expected_version": 2},
        headers=headers,
    )
    note_id = confirmed.json()["id"]
    assert client.get("/api/notes").json()[0]["id"] == note_id
    assert client.get(f"/api/notes/{note_id}").json()["version"] == 1
    assert client.get("/api/words/deployment").json()["notes"][0]["id"] == note_id

    preview = client.get(f"/api/notes/{note_id}/preview")
    assert preview.status_code == 200
    rendered = preview.json()
    assert rendered["template_version"] == 4
    assert "The deployment is complete." in rendered["front_html"]
    assert "部署完成了。" not in rendered["front_html"]
    assert "部署完成了。" in rendered["back_html"]
    assert "acc-front" not in rendered["back_html"]
    assert client.get(f"/api/notes/{note_id}/media/example_audio").status_code == 404

    assert client.post("/api/anki/template/sync").status_code == 403
    synced = client.post("/api/anki/template/sync", headers=headers)
    assert synced.status_code == 200
    assert synced.json()["template_version"] == 4
    assert services.anki.templates[0]["Front"] == FRONT_TEMPLATE
    assert services.anki.css == CSS

    whole_word = client.post("/api/words/deployment/regenerate", headers=headers)
    one_note = client.post(f"/api/notes/{note_id}/regenerate", headers=headers)
    assert whole_word.status_code == 202 and one_note.status_code == 202
    assert one_note.json()["generation_id"] == whole_word.json()["generation_ids"][0]

    changed = client.patch(
        f"/api/notes/{note_id}",
        json={"expected_version": 1, "changes": {"usage_notes": "Used in DevOps."}},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    publish_job_id = changed.json()["job_id"]
    assert client.get(f"/api/jobs/{publish_job_id}").json()["type"] == "publish"
    assert client.post(f"/api/notes/{note_id}/publish", json={}, headers=headers).status_code == 202
    inspected = client.post(f"/api/notes/{note_id}/inspect-anki", headers=headers)
    assert inspected.status_code == 202
    assert client.get(f"/api/jobs/{inspected.json()['job_id']}").json()["type"] == "inspect"
    assert len(client.get("/api/jobs").json()) >= 2
    assert client.delete(f"/api/notes/{note_id}", headers=headers).status_code == 409

    archived = client.post(f"/api/notes/{note_id}/archive", headers=headers)
    assert archived.status_code == 202 and archived.json()["status"] == "archived"
    assert client.delete(f"/api/notes/{note_id}", headers=headers).status_code == 204
    assert client.get(f"/api/notes/{note_id}").status_code == 404
    assert client.delete(f"/api/notes/{note_id}", headers=headers).status_code == 404
    assert client.post(f"/api/notes/{note_id}/regenerate", headers=headers).status_code == 404
    assert client.post(f"/api/notes/{note_id}/publish", json={}, headers=headers).status_code == 404
    assert client.get("/api/jobs/missing").status_code == 404


def test_failed_jobs_can_be_listed_and_retried(web_app) -> None:
    client, services = web_app
    token = csrf(client)
    with services.sessions.begin() as session:
        failed = Job(
            job_type="inspect",
            aggregate_id="manual",
            status="failed",
            available_at=datetime.now(UTC),
            max_attempts=3,
            attempts=3,
            last_error="offline",
        )
        session.add(failed)
        session.flush()
        job_id = failed.id

    listed = client.get("/api/jobs?status=failed").json()
    assert [item["id"] for item in listed] == [job_id]
    retried = client.post(f"/api/jobs/{job_id}/retry", headers={"X-CSRF-Token": token})
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
