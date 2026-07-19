from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.domain.notes import NoteCreate, NoteUpdate
from anki_custom_card.integrations.anki_connect.client import AnkiConnectError
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.database import build_engine
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import AnkiPublication, Base, Note
from anki_custom_card.persistence.note_repository import NoteRepository
from anki_custom_card.publishing.commands import (
    request_archive,
    request_inspection,
    request_publish,
)
from anki_custom_card.publishing.inspection import AnkiInspectionService
from anki_custom_card.publishing.jobs import PublicationJobHandler
from anki_custom_card.publishing.note_type import FIELDS, NOTE_TYPE_NAME
from anki_custom_card.publishing.service import PublicationService

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = build_engine(f"sqlite:///{tmp_path / 'publishing.db'}")
    Base.metadata.create_all(value)
    yield value
    value.dispose()


def create_note(engine: Engine, store: ContentAddressedMediaStore) -> str:
    with Session(engine) as session:
        note = NoteRepository(session).create(
            NoteCreate(
                language="en",
                word_display="deploy",
                domain="it",
                part_of_speech="verb",
                definition_en="To release software to an environment.",
                definition_zh="部署",
                example="We deploy after the build passes.",
                example_zh="构建通过后我们进行部署。",
                pronunciation="/dɪˈplɔɪ/",  # noqa: RUF001 - IPA transcription
                collocations=[{"text": "deploy a service"}],
            )
        )
        MediaRepository(session, store).add_and_link(
            note.id,
            content=b"word-mp3",
            media_type="audio",
            mime_type="audio/mpeg",
            usage="word_audio",
        )
        session.commit()
        return note.id


class FakeAnki:
    def __init__(self) -> None:
        self.decks: list[str] = []
        self.models: list[str] = []
        self.notes: dict[int, dict[str, str]] = {}
        self.next_id = 100
        self.add_count = 0
        self.update_count = 0
        self.media: dict[str, bytes] = {}

    async def deck_names(self):
        return self.decks

    async def create_deck(self, name):
        self.decks.append(name)
        return 1

    async def model_names(self):
        return self.models

    async def model_field_names(self, name):
        return FIELDS

    async def create_model(self, **values):
        self.models.append(values["name"])
        return values

    async def store_media(self, *, filename, content):
        self.media[filename] = content
        return filename

    async def find_notes(self, query):
        source_id = query.removeprefix('"SourceId:').removesuffix('"')
        return [
            note_id for note_id, fields in self.notes.items() if fields["SourceId"] == source_id
        ]

    async def add_note(self, *, deck, model, fields, tags):
        assert model == NOTE_TYPE_NAME
        self.add_count += 1
        note_id = self.next_id
        self.next_id += 1
        self.notes[note_id] = dict(fields)
        return note_id

    async def update_note(self, note_id, *, fields, tags):
        self.update_count += 1
        self.notes[note_id] = dict(fields)

    async def notes_info(self, note_ids):
        return [
            {
                "noteId": note_id,
                "fields": {
                    name: {"value": value, "order": index}
                    for index, (name, value) in enumerate(self.notes[note_id].items())
                },
            }
            for note_id in note_ids
            if note_id in self.notes
        ]

    async def delete_notes(self, note_ids):
        for note_id in note_ids:
            self.notes.pop(note_id, None)


@pytest.mark.anyio
async def test_publish_is_idempotent_and_updates_a_new_version(
    engine: Engine, tmp_path: Path
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    note_id = create_note(engine, store)
    factory = sessionmaker(engine, expire_on_commit=False)
    gateway = FakeAnki()
    service = PublicationService(factory, gateway, store)

    anki_id = await service.publish(note_id, 1)
    assert await service.publish(note_id, 1) == anki_id
    assert gateway.add_count == 1
    assert gateway.media[next(iter(gateway.media))] == b"word-mp3"
    assert gateway.notes[anki_id]["WordAudio"].startswith("[sound:acc_")

    with factory.begin() as session:
        NoteRepository(session).update(
            note_id,
            expected_version=1,
            changes=NoteUpdate(example="We deploy continuously."),
        )
    await service.publish(note_id, 2)
    assert gateway.add_count == 1
    assert gateway.update_count == 1
    assert gateway.notes[anki_id]["Example"] == "We deploy continuously."
    with factory() as session:
        publication = session.get(AnkiPublication, note_id)
        assert publication is not None
        assert publication.status == "published"
        assert publication.published_version == 2


@pytest.mark.anyio
async def test_publish_recovers_mapping_by_source_id(engine: Engine, tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    note_id = create_note(engine, store)
    gateway = FakeAnki()
    gateway.notes[42] = {name: (note_id if name == "SourceId" else "old") for name in FIELDS}
    service = PublicationService(sessionmaker(engine, expire_on_commit=False), gateway, store)

    assert await service.publish(note_id, 1) == 42
    assert gateway.add_count == 0
    assert gateway.update_count == 1


@pytest.mark.anyio
async def test_inspection_detects_drift_and_missing_without_changing_local_note(
    engine: Engine, tmp_path: Path
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    note_id = create_note(engine, store)
    factory = sessionmaker(engine, expire_on_commit=False)
    gateway = FakeAnki()
    publication_service = PublicationService(factory, gateway, store)
    anki_id = await publication_service.publish(note_id, 1)
    inspector = AnkiInspectionService(factory, gateway)

    assert (await inspector.inspect(note_id)).status == "published"
    now = datetime.now(UTC)
    with factory.begin() as session:
        inspection_job = request_inspection(session, note_id, now=now)
        inspection_job_id = inspection_job.id
    with factory.begin() as session:
        claimed = JobRepository(session).claim("inspector", now, timedelta(minutes=1))
        assert claimed is not None and claimed.id == inspection_job_id
    completed = await PublicationJobHandler(factory, publication_service, inspector).run(
        inspection_job_id, worker_id="inspector"
    )
    assert completed.status == "succeeded"

    gateway.notes[anki_id]["DefinitionEn"] = "A manual Anki edit."
    drift = await inspector.inspect(note_id)
    assert drift.status == "drifted"
    assert drift.changed_fields == ("DefinitionEn",)
    with factory() as session:
        note = session.get(Note, note_id)
        publication = session.get(AnkiPublication, note_id)
        assert note is not None
        assert note.definition_en == "To release software to an environment."
        assert publication is not None and publication.status == "drifted"

    original_notes_info = gateway.notes_info

    async def unavailable(note_ids: list[int]) -> list[dict[str, Any]]:
        raise AnkiConnectError("anki_unavailable", "offline", retryable=True)

    gateway.notes_info = unavailable  # type: ignore[method-assign]
    with pytest.raises(AnkiConnectError):
        await inspector.inspect(note_id)
    with factory() as session:
        publication = session.get(AnkiPublication, note_id)
        assert publication is not None and publication.status == "drifted"

    gateway.notes_info = original_notes_info  # type: ignore[method-assign]
    gateway.notes.pop(anki_id)
    assert (await inspector.inspect(note_id)).status == "missing"
    with factory() as session:
        publication = session.get(AnkiPublication, note_id)
        assert publication is not None and publication.status == "missing"


@pytest.mark.anyio
async def test_archive_persists_delete_intent_and_confirms_absence(
    engine: Engine,
    tmp_path: Path,
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    note_id = create_note(engine, store)
    factory = sessionmaker(engine, expire_on_commit=False)
    gateway = FakeAnki()
    service = PublicationService(factory, gateway, store)
    anki_id = await service.publish(note_id, 1)

    with factory.begin() as session:
        assert request_archive(session, note_id, now=datetime.now(UTC)) is True
    with factory() as session:
        assert session.get(Note, note_id).status == "archive_pending"  # type: ignore[union-attr]
        job = JobRepository(session).claim(
            "worker", datetime.now(UTC), __import__("datetime").timedelta(minutes=1)
        )
        assert job is not None and job.job_type == "delete_anki"

    await service.delete_archived(note_id)
    assert anki_id not in gateway.notes
    with factory() as session:
        assert session.get(Note, note_id).status == "archived"  # type: ignore[union-attr]
        publication = session.get(AnkiPublication, note_id)
        assert publication is not None
        assert publication.status == "deleted"
        assert publication.anki_note_id == anki_id
        assert publication.last_error_code is None
        assert publication.last_error_message is None


def test_archive_without_remote_mapping_creates_deleted_tombstone(
    engine: Engine,
    tmp_path: Path,
) -> None:
    note_id = create_note(engine, ContentAddressedMediaStore(tmp_path / "media"))
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        assert request_archive(session, note_id, now=datetime.now(UTC)) is False
    with factory() as session:
        assert session.get(Note, note_id).status == "archived"  # type: ignore[union-attr]
        assert session.get(AnkiPublication, note_id).status == "deleted"  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_worker_enqueues_latest_version_when_note_changes_during_publish(
    engine: Engine,
    tmp_path: Path,
) -> None:
    store = ContentAddressedMediaStore(tmp_path / "media")
    note_id = create_note(engine, store)
    factory = sessionmaker(engine, expire_on_commit=False)
    gateway = FakeAnki()
    service = PublicationService(factory, gateway, store)
    now = datetime.now(UTC)
    with factory.begin() as session:
        request_publish(session, note_id, 1, now=now)
    with factory.begin() as session:
        job = JobRepository(session).claim("worker", now, timedelta(minutes=5))
        assert job is not None
        job_id = job.id

    original_add = gateway.add_note

    async def add_and_change(**values: Any) -> int:
        result = await original_add(**values)
        with factory.begin() as session:
            NoteRepository(session).update(
                note_id,
                expected_version=1,
                changes=NoteUpdate(example="Version two arrived during publication."),
            )
        return result

    gateway.add_note = add_and_change  # type: ignore[method-assign]
    completed = await PublicationJobHandler(factory, service).run(job_id, worker_id="worker")
    assert completed.status == "succeeded"
    with factory() as session:
        next_job = (
            session.query(type(completed))
            .filter_by(job_type="publish", aggregate_id=note_id, status="pending")
            .one()
        )
        assert next_job.target_version == 2
        assert session.get(AnkiPublication, note_id).status == "pending"  # type: ignore[union-attr]
