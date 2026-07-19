import hashlib
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.integrations.anki_connect.client import AnkiConnectError
from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.models import Media, Note, NoteMedia, NoteRevision
from anki_custom_card.persistence.publication_repository import PublicationRepository
from anki_custom_card.publishing.note_type import NOTE_TYPE_NAME, NoteTypeManager
from anki_custom_card.publishing.ports import AnkiGateway


class DuplicateSourceIdError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaSnapshot:
    usage: str
    sha256: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class PublishSnapshot:
    note_id: str
    target_version: int
    deck: str
    anki_note_id: int | None
    content: dict[str, Any]
    media: tuple[MediaSnapshot, ...]


def fields_hash(fields: dict[str, str]) -> str:
    value = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _text(value: object) -> str:
    return html.escape(str(value)) if value is not None else ""


def render_fields(
    note_id: str, content: dict[str, Any], media_names: dict[str, str]
) -> dict[str, str]:
    collocations = content.get("collocations", [])
    collocation_text = "; ".join(
        str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in collocations
    )
    return {
        "SourceId": note_id,
        "Word": _text(content.get("word_display")),
        "Domain": _text(content.get("domain")),
        "PartOfSpeech": _text(content.get("part_of_speech")),
        "Pronunciation": _text(content.get("pronunciation")),
        "DefinitionEn": _text(content.get("definition_en")),
        "DefinitionZh": _text(content.get("definition_zh")),
        "Example": _text(content.get("example")),
        "ExampleZh": _text(content.get("example_zh")),
        "Collocations": _text(collocation_text),
        "UsageNotes": _text(content.get("usage_notes")),
        "WordAudio": f"[sound:{media_names['word_audio']}]" if "word_audio" in media_names else "",
        "ExampleAudio": (
            f"[sound:{media_names['example_audio']}]" if "example_audio" in media_names else ""
        ),
        "Extra": _text(content.get("extra")),
    }


class PublicationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: AnkiGateway,
        media_store: ContentAddressedMediaStore,
        *,
        deck: str = "Anki Custom Card",
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway
        self.media_store = media_store
        self.deck = deck

    async def publish(self, note_id: str, target_version: int) -> int:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            existing = PublicationRepository(session).get(note_id)
            if (
                existing is not None
                and existing.status == "published"
                and existing.published_version == target_version
                and existing.anki_note_id is not None
            ):
                return existing.anki_note_id
        snapshot = self._begin(note_id, target_version, now)
        try:
            await NoteTypeManager(self.gateway).ensure(snapshot.deck)
            media_names: dict[str, str] = {}
            for item in snapshot.media:
                suffix = Path(item.relative_path).suffix
                filename = f"acc_{item.sha256}{suffix}"
                media_names[item.usage] = await self.gateway.store_media(
                    filename=filename, content=self.media_store.read(item.relative_path)
                )
            fields = render_fields(note_id, snapshot.content, media_names)
            anki_note_id = await self._resolve_note_id(snapshot, fields)
            tags = ["anki_custom_card", f"acc_v{target_version}"]
            if anki_note_id is None:
                anki_note_id = await self.gateway.add_note(
                    deck=snapshot.deck, model=NOTE_TYPE_NAME, fields=fields, tags=tags
                )
            else:
                await self.gateway.update_note(anki_note_id, fields=fields, tags=tags)
            info = await self.gateway.notes_info([anki_note_id])
            if len(info) != 1:
                raise AnkiConnectError(
                    "anki_publish_unconfirmed",
                    "published Note could not be read back",
                    retryable=True,
                )
            observed_fields = {
                name: str(value.get("value", "")) for name, value in info[0]["fields"].items()
            }
            expected_hash = fields_hash(fields)
            observed_hash = fields_hash(observed_fields)
            if observed_hash != expected_hash:
                raise AnkiConnectError(
                    "anki_publish_mismatch", "Anki fields differ after publication", retryable=True
                )
        except Exception as error:
            self._record_failure(note_id, error, datetime.now(UTC))
            raise
        with self.session_factory.begin() as session:
            PublicationRepository(session).succeed(
                note_id,
                target_version=target_version,
                anki_note_id=anki_note_id,
                published_hash=expected_hash,
                observed_hash=observed_hash,
                now=datetime.now(UTC),
            )
        return anki_note_id

    def _begin(self, note_id: str, target_version: int, now: datetime) -> PublishSnapshot:
        with self.session_factory.begin() as session:
            note = session.get(Note, note_id)
            revision = session.get(NoteRevision, (note_id, target_version))
            if note is None or revision is None:
                raise LookupError(f"Note {note_id} version {target_version} was not found")
            if note.status != "active":
                raise ValueError(f"Note {note_id} is not active")
            repo = PublicationRepository(session)
            publication = repo.ensure(note_id, deck=self.deck, note_type=NOTE_TYPE_NAME)
            repo.begin(note_id, target_version=target_version, now=now)
            rows = session.execute(
                select(NoteMedia.usage, Media.sha256, Media.relative_path)
                .join(Media, Media.id == NoteMedia.media_id)
                .where(NoteMedia.note_id == note_id)
            )
            media = tuple(MediaSnapshot(*row) for row in rows)
            return PublishSnapshot(
                note_id,
                target_version,
                publication.target_deck,
                publication.anki_note_id,
                dict(revision.content),
                media,
            )

    async def _resolve_note_id(
        self, snapshot: PublishSnapshot, fields: dict[str, str]
    ) -> int | None:
        if snapshot.anki_note_id is not None and await self.gateway.notes_info(
            [snapshot.anki_note_id]
        ):
            return snapshot.anki_note_id
        matches = await self.gateway.find_notes(f'"SourceId:{fields["SourceId"]}"')
        if len(matches) > 1:
            raise DuplicateSourceIdError(f"multiple Anki Notes have SourceId {snapshot.note_id}")
        return matches[0] if matches else None

    def _record_failure(self, note_id: str, error: Exception, now: datetime) -> None:
        code = getattr(error, "code", "publish_failed")
        with self.session_factory.begin() as session:
            PublicationRepository(session).fail(
                note_id, code=str(code), message=str(error), now=now
            )

    async def delete_archived(self, note_id: str) -> None:
        with self.session_factory() as session:
            publication = PublicationRepository(session).get(note_id)
            if publication is None:
                raise LookupError(note_id)
            anki_note_id = publication.anki_note_id
        try:
            if anki_note_id is not None:
                if await self.gateway.notes_info([anki_note_id]):
                    await self.gateway.delete_notes([anki_note_id])
                if await self.gateway.notes_info([anki_note_id]):
                    raise AnkiConnectError(
                        "anki_delete_unconfirmed",
                        "Anki Note still exists after deletion",
                        retryable=True,
                    )
        except Exception as error:
            with self.session_factory.begin() as session:
                PublicationRepository(session).fail_deletion(
                    note_id,
                    code=str(getattr(error, "code", "anki_delete_failed")),
                    message=str(error),
                    now=datetime.now(UTC),
                )
            raise
        with self.session_factory.begin() as session:
            PublicationRepository(session).complete_deletion(note_id, now=datetime.now(UTC))
