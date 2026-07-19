from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.models import Media, NoteMedia, new_id


class MediaRepository:
    def __init__(self, session: Session, store: ContentAddressedMediaStore) -> None:
        self.session = session
        self.store = store

    def add_and_link(
        self,
        note_id: str,
        *,
        content: bytes,
        media_type: str,
        mime_type: str,
        usage: str,
    ) -> Media:
        media = self.add(content=content, media_type=media_type, mime_type=mime_type)

        existing_link = self.session.get(NoteMedia, (note_id, usage))
        if existing_link is not None:
            if existing_link.media_id == media.id:
                return media
            raise ValueError(f"Note {note_id} already has media for usage {usage}")

        self.session.add(NoteMedia(note_id=note_id, media_id=media.id, usage=usage))
        self.session.flush()
        return media

    def add(self, *, content: bytes, media_type: str, mime_type: str) -> Media:
        stored = self.store.put(content, media_type=media_type, mime_type=mime_type)
        self.session.execute(
            sqlite_insert(Media)
            .values(
                id=new_id(),
                sha256=stored.sha256,
                media_type=stored.media_type,
                mime_type=stored.mime_type,
                byte_size=stored.byte_size,
                relative_path=stored.relative_path,
            )
            .on_conflict_do_nothing(index_elements=[Media.sha256])
        )
        media = self.session.scalar(select(Media).where(Media.sha256 == stored.sha256))
        if media is None:  # pragma: no cover - guarded by the insert/select transaction
            raise RuntimeError(f"Failed to persist media {stored.sha256}")

        return media

    def delete_unreferenced(self) -> list[str]:
        unreferenced = list(
            self.session.scalars(
                select(Media).where(
                    ~Media.links.any(),
                    ~Media.artifacts.any(),
                    ~Media.speech_cache_entries.any(),
                )
            )
        )
        if not unreferenced:
            return []

        paths = [media.relative_path for media in unreferenced]
        self.session.execute(
            delete(Media).where(Media.id.in_([media.id for media in unreferenced]))
        )
        self.session.flush()
        return paths

    def delete_files(self, relative_paths: list[str]) -> None:
        for relative_path in relative_paths:
            self.store.delete(relative_path)
