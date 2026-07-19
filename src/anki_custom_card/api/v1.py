from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from anki_custom_card.deletion import ArchivedNoteRequiredError
from anki_custom_card.domain.notes import NoteUpdate
from anki_custom_card.domain.words import normalize_english_word
from anki_custom_card.generation.commands import (
    request_note_regeneration,
    request_word_generation,
)
from anki_custom_card.generation.schemas import CardDraft
from anki_custom_card.persistence.draft_repository import DraftRepository
from anki_custom_card.persistence.generation_repository import GenerationRepository
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Draft, GenerationJob, Job, Media, Note, NoteMedia
from anki_custom_card.persistence.note_repository import (
    NoteNotFoundError,
    NoteRepository,
    revision_content,
)
from anki_custom_card.publishing.commands import (
    request_archive,
    request_inspection,
    request_publish,
)
from anki_custom_card.publishing.note_type import (
    CSS,
    NOTE_TYPE_NAME,
    NOTE_TYPE_VERSION,
    NoteTypeManager,
    render_card_preview,
)
from anki_custom_card.publishing.service import render_fields
from anki_custom_card.services import ApplicationServices

router = APIRouter(prefix="/api", tags=["application"])


def services(request: Request) -> ApplicationServices:
    return request.app.state.services


AppServices = Annotated[ApplicationServices, Depends(services)]


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get("acc_csrf")
    header = request.headers.get("X-CSRF-Token")
    if not cookie or header != cookie:
        raise HTTPException(status_code=403, detail="invalid CSRF token")


class GenerationCreateRequest(BaseModel):
    word: str = Field(min_length=1, max_length=512)
    notes_per_word: int = Field(default=3, ge=1, le=5)


class ConfirmDraftRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_note_version: int | None = Field(default=None, ge=1)


class PublishRequest(BaseModel):
    target_version: int | None = Field(default=None, ge=1)


class NoteUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    changes: NoteUpdate


def generation_data(job: GenerationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "word": job.input_word,
        "language": job.language,
        "status": job.status,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "draft_id": job.draft.id if job.draft is not None else None,
        "source_note_id": job.source_note_id,
        "word_idx": job.provider_config.get("word_idx"),
        "created_at": job.created_at,
    }


def note_data(note: Note) -> dict[str, Any]:
    publication = note.publication
    return {
        "id": note.id,
        "word": note.word_display,
        "word_idx": note.word_idx,
        "domain": note.domain,
        "status": note.status,
        "version": note.version,
        "definition_en": note.definition_en,
        "definition_zh": note.definition_zh,
        "example": note.example,
        "example_zh": note.example_zh,
        "part_of_speech": note.part_of_speech,
        "pronunciation": note.pronunciation,
        "collocations": note.collocations,
        "usage_notes": note.usage_notes,
        "extra": note.extra,
        "publication": None
        if publication is None
        else {
            "status": publication.status,
            "published_version": publication.published_version,
            "anki_note_id": publication.anki_note_id,
        },
    }


@router.post(
    "/generations", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_csrf)]
)
def create_generation(payload: GenerationCreateRequest, app: AppServices):
    now = datetime.now(UTC)
    with app.sessions.begin() as session:
        generations = request_word_generation(
            session, payload.word, now=now, candidate_count=payload.notes_per_word
        )
        result = {"generation_ids": [item.id for item in generations], "status": "pending"}
    app.worker.notify()
    return result


@router.get("/generations/{generation_id}")
def get_generation(generation_id: str, app: AppServices):
    with app.sessions() as session:
        job = GenerationRepository(session).get_job(generation_id)
        return generation_data(job)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, app: AppServices):
    with app.sessions() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(404, "draft not found")
        return {
            "id": draft.id,
            "status": draft.status,
            "version": draft.version,
            "content": draft.content,
        }


@router.patch("/drafts/{draft_id}", dependencies=[Depends(require_csrf)])
def update_draft(
    draft_id: str,
    content: CardDraft,
    expected_version: int,
    app: AppServices,
):
    with app.sessions.begin() as session:
        draft = DraftRepository(session).update(
            draft_id, expected_version=expected_version, content=content
        )
        return {
            "id": draft.id,
            "status": draft.status,
            "version": draft.version,
            "content": draft.content,
        }


@router.post("/drafts/{draft_id}/confirm", dependencies=[Depends(require_csrf)])
def confirm_draft(
    draft_id: str,
    payload: ConfirmDraftRequest,
    app: AppServices,
):
    with app.sessions.begin() as session:
        note = DraftRepository(session).confirm(
            draft_id,
            expected_version=payload.expected_version,
            expected_note_version=payload.expected_note_version,
            domain=None,
            now=datetime.now(UTC),
        )
        result = note_data(note)
    app.worker.notify()
    return result


@router.post("/words/{word}/regenerate", status_code=202, dependencies=[Depends(require_csrf)])
def regenerate_word(word: str, app: AppServices):
    with app.sessions.begin() as session:
        generations = request_word_generation(session, word, now=datetime.now(UTC))
        result = {"generation_ids": [item.id for item in generations]}
    app.worker.notify()
    return result


@router.get("/words")
def list_words(app: AppServices):
    with app.sessions() as session:
        notes = list(session.scalars(select(Note).order_by(Note.word_normalized, Note.word_idx)))
        generations = list(
            session.scalars(select(GenerationJob).order_by(GenerationJob.created_at.desc()))
        )
        groups: dict[str, dict[str, Any]] = {}
        for note in notes:
            group = groups.setdefault(
                note.word_normalized,
                {
                    "word": note.word_display,
                    "normalized": note.word_normalized,
                    "notes": [],
                    "generations": [],
                },
            )
            group["notes"].append(note_data(note))
        for generation in generations:
            normalized = normalize_english_word(generation.input_word)
            group = groups.setdefault(
                normalized,
                {
                    "word": generation.input_word.strip(),
                    "normalized": normalized,
                    "notes": [],
                    "generations": [],
                },
            )
            group["generations"].append(generation_data(generation))
        return list(groups.values())


@router.get("/words/{word}")
def get_word(word: str, app: AppServices):
    normalized = normalize_english_word(word)
    with app.sessions() as session:
        notes = list(
            session.scalars(
                select(Note)
                .where(Note.language == "en", Note.word_normalized == normalized)
                .order_by(Note.word_idx)
            )
        )
        generations = [
            item
            for item in session.scalars(
                select(GenerationJob).order_by(GenerationJob.created_at.desc())
            )
            if normalize_english_word(item.input_word) == normalized
        ]
        if not notes and not generations:
            raise HTTPException(404, "word not found")
        return {
            "word": notes[0].word_display if notes else generations[0].input_word,
            "normalized": normalized,
            "notes": [note_data(note) for note in notes],
            "generations": [generation_data(item) for item in generations],
        }


@router.post("/notes/{note_id}/regenerate", status_code=202, dependencies=[Depends(require_csrf)])
def regenerate_note(note_id: str, app: AppServices):
    with app.sessions.begin() as session:
        note = session.get(Note, note_id)
        if note is None:
            raise HTTPException(404, "note not found")
        generation = request_note_regeneration(session, note, now=datetime.now(UTC))
        result = {"generation_id": generation.id}
    app.worker.notify()
    return result


@router.get("/notes/{note_id}/preview")
def preview_note(note_id: str, app: AppServices):
    with app.sessions() as session:
        note = session.get(Note, note_id)
        if note is None:
            raise HTTPException(404, "note not found")
        usages = set(session.scalars(select(NoteMedia.usage).where(NoteMedia.note_id == note_id)))
        fields = render_fields(note.id, revision_content(note), {})
        if "word_audio" in usages:
            source = f"/api/notes/{note_id}/media/word_audio"
            fields["WordAudio"] = f'<audio controls preload="none" src="{source}"></audio>'
        if "example_audio" in usages:
            source = f"/api/notes/{note_id}/media/example_audio"
            fields["ExampleAudio"] = f'<audio controls preload="none" src="{source}"></audio>'
        front, back = render_card_preview(fields)
        return {
            "note_id": note.id,
            "note_version": note.version,
            "template_version": NOTE_TYPE_VERSION,
            "front_html": front,
            "back_html": back,
            "css": CSS,
        }


@router.get("/notes/{note_id}/media/{usage}")
def preview_media(note_id: str, usage: str, app: AppServices) -> Response:
    with app.sessions() as session:
        row = session.execute(
            select(Media.relative_path, Media.mime_type)
            .join(NoteMedia, NoteMedia.media_id == Media.id)
            .where(NoteMedia.note_id == note_id, NoteMedia.usage == usage)
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "media not found")
        content = app.media_store.read(row.relative_path)
        return Response(content=content, media_type=row.mime_type)


@router.post("/anki/template/sync", dependencies=[Depends(require_csrf)])
async def sync_anki_template(app: AppServices):
    await NoteTypeManager(app.anki).ensure(app.settings.anki_deck)
    return {
        "status": "synchronized",
        "note_type": NOTE_TYPE_NAME,
        "template_version": NOTE_TYPE_VERSION,
    }


@router.get("/notes")
def list_notes(app: AppServices):
    with app.sessions() as session:
        return [
            note_data(note)
            for note in session.scalars(select(Note).order_by(Note.updated_at.desc(), Note.id))
        ]


@router.get("/notes/{note_id}")
def get_note(note_id: str, app: AppServices):
    with app.sessions() as session:
        note = NoteRepository(session).get(note_id)
        if note is None:
            raise HTTPException(404, "note not found")
        return note_data(note)


@router.patch("/notes/{note_id}", dependencies=[Depends(require_csrf)])
def update_note(
    note_id: str,
    payload: NoteUpdateRequest,
    app: AppServices,
):
    with app.sessions.begin() as session:
        note = NoteRepository(session).update(
            note_id, expected_version=payload.expected_version, changes=payload.changes
        )
        job = request_publish(
            session, note.id, note.version, now=datetime.now(UTC), deck=app.settings.anki_deck
        )
        result = note_data(note)
        result["job_id"] = job.id
    app.worker.notify()
    return result


@router.post("/notes/{note_id}/publish", status_code=202, dependencies=[Depends(require_csrf)])
def publish_note(
    note_id: str,
    payload: PublishRequest,
    app: AppServices,
):
    with app.sessions.begin() as session:
        note = session.get(Note, note_id)
        if note is None:
            raise HTTPException(404, "note not found")
        job = request_publish(
            session,
            note_id,
            payload.target_version or note.version,
            now=datetime.now(UTC),
            deck=app.settings.anki_deck,
        )
        result = {"job_id": job.id, "target_version": job.target_version}
    app.worker.notify()
    return result


@router.post("/notes/{note_id}/inspect-anki", status_code=202, dependencies=[Depends(require_csrf)])
def inspect_note(note_id: str, app: AppServices):
    with app.sessions.begin() as session:
        job = request_inspection(session, note_id, now=datetime.now(UTC))
        result = {"job_id": job.id}
    app.worker.notify()
    return result


@router.post("/notes/{note_id}/archive", status_code=202, dependencies=[Depends(require_csrf)])
def archive_note(note_id: str, app: AppServices):
    with app.sessions.begin() as session:
        remote = request_archive(session, note_id, now=datetime.now(UTC))
    app.worker.notify()
    return {"status": "archive_pending" if remote else "archived"}


@router.delete("/notes/{note_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_note(note_id: str, app: AppServices) -> Response:
    try:
        app.note_deletion.delete(note_id)
    except NoteNotFoundError as error:
        raise HTTPException(404, "note not found") from error
    except ArchivedNoteRequiredError as error:
        raise HTTPException(409, str(error)) from error
    return Response(status_code=204)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, app: AppServices):
    with app.sessions() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "attempts": job.attempts,
            "last_error": job.last_error,
        }


@router.get("/jobs")
def list_jobs(app: AppServices, status: str | None = None):
    with app.sessions() as session:
        statement = select(Job).order_by(Job.updated_at.desc()).limit(100)
        if status is not None:
            statement = statement.where(Job.status == status)
        return [
            {
                "id": job.id,
                "type": job.job_type,
                "status": job.status,
                "attempts": job.attempts,
                "last_error": job.last_error,
            }
            for job in session.scalars(statement)
        ]


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(require_csrf)])
def retry_job(job_id: str, app: AppServices):
    with app.sessions.begin() as session:
        job = JobRepository(session).retry_failed(job_id, now=datetime.now(UTC))
        result = {"id": job.id, "status": job.status}
    app.worker.notify()
    return result
