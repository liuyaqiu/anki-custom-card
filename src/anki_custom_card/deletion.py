from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from anki_custom_card.media.store import ContentAddressedMediaStore
from anki_custom_card.persistence.media_repository import MediaRepository
from anki_custom_card.persistence.models import (
    Draft,
    GenerationJob,
    Job,
    Media,
    Note,
    NoteMedia,
    SpeechCacheEntry,
)
from anki_custom_card.persistence.note_repository import NoteNotFoundError


class ArchivedNoteRequiredError(ValueError):
    pass


class NoteDeletionService:
    """Permanently remove an archived Note and data exclusively owned by it."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        media_store: ContentAddressedMediaStore,
    ) -> None:
        self.session_factory = session_factory
        self.media_store = media_store

    def delete(self, note_id: str) -> None:
        with self.session_factory.begin() as session:
            note = session.get(Note, note_id)
            if note is None:
                raise NoteNotFoundError(note_id)
            if note.status != "archived":
                raise ArchivedNoteRequiredError(
                    f"Note {note_id} must be archived before permanent deletion"
                )

            generation_ids = list(
                session.scalars(
                    select(GenerationJob.id).where(
                        or_(
                            GenerationJob.source_note_id == note_id,
                            GenerationJob.draft.has(Draft.confirmed_note_id == note_id),
                        )
                    )
                )
            )
            media_ids = list(
                session.scalars(select(NoteMedia.media_id).where(NoteMedia.note_id == note_id))
            )

            aggregate_ids = [note_id, *generation_ids]
            session.execute(delete(Job).where(Job.aggregate_id.in_(aggregate_ids)))
            if generation_ids:
                session.execute(delete(GenerationJob).where(GenerationJob.id.in_(generation_ids)))
            session.delete(note)
            session.flush()

            if media_ids:
                disposable_media = select(Media.id).where(
                    Media.id.in_(media_ids),
                    ~Media.links.any(),
                    ~Media.artifacts.any(),
                )
                session.execute(
                    delete(SpeechCacheEntry).where(SpeechCacheEntry.media_id.in_(disposable_media))
                )
                session.flush()

            paths = MediaRepository(session, self.media_store).delete_unreferenced()

        MediaRepository.delete_files_from_store(self.media_store, paths)
