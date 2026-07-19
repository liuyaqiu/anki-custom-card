import hashlib
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from anki_custom_card.domain.words import normalize_english_word
from anki_custom_card.persistence.generation_repository import GenerationRepository
from anki_custom_card.persistence.job_repository import JobRepository
from anki_custom_card.persistence.models import Draft, GenerationJob, Note

DEFAULT_CANDIDATE_COUNT = 3


def request_word_generation(
    session: Session,
    word: str,
    *,
    now: datetime,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
) -> list[GenerationJob]:
    normalized = normalize_english_word(word)
    all_notes = list(
        session.scalars(
            select(Note)
            .where(Note.language == "en", Note.word_normalized == normalized)
            .order_by(Note.word_idx)
        )
    )
    existing = [note for note in all_notes if note.status == "active"]
    if existing:
        return [request_note_regeneration(session, note, now=now) for note in existing]
    if not 1 <= candidate_count <= 5:
        raise ValueError("candidate_count must be between 1 and 5")
    start_index = max((note.word_idx for note in all_notes), default=-1) + 1
    return [
        _enqueue(
            session,
            word,
            word_idx=start_index + offset,
            source_note_id=None,
            source_version=None,
            now=now,
            mode="initial",
        )
        for offset in range(candidate_count)
    ]


def request_note_regeneration(session: Session, note: Note, *, now: datetime) -> GenerationJob:
    if note.status != "active":
        raise ValueError(f"Note {note.id} is not active")
    return _enqueue(
        session,
        note.word_display,
        word_idx=note.word_idx,
        source_note_id=note.id,
        source_version=note.version,
        now=now,
        mode="regenerate",
    )


def _enqueue(
    session: Session,
    word: str,
    *,
    word_idx: int,
    source_note_id: str | None,
    source_version: int | None,
    now: datetime,
    mode: str,
) -> GenerationJob:
    normalized = normalize_english_word(word)
    identity = (
        f"regenerate:{source_note_id}:{source_version}"
        if source_note_id is not None
        else f"initial:en:{normalized}:{word_idx}"
    )
    request_key = hashlib.sha256(identity.encode()).hexdigest()
    existing = session.scalar(select(GenerationJob).where(GenerationJob.request_key == request_key))
    if existing is None:
        existing = _legacy_outstanding_generation(
            session,
            normalized=normalized,
            word_idx=word_idx,
            source_note_id=source_note_id,
        )
    if existing is not None:
        return existing

    try:
        with session.begin_nested():
            generation = GenerationRepository(session).create_job(
                word,
                "en",
                now=now,
                source_note_id=source_note_id,
                request_key=request_key,
                provider_config={
                    "mode": mode,
                    "word_idx": word_idx,
                    "english_variant": "en-US",
                },
            )
            JobRepository(session).enqueue(
                job_type="generate",
                aggregate_id=generation.id,
                payload={"word_idx": word_idx},
                now=now,
            )
        return generation
    except IntegrityError:
        concurrent = session.scalar(
            select(GenerationJob).where(GenerationJob.request_key == request_key)
        )
        if concurrent is None:  # pragma: no cover - defensive against unrelated constraints
            raise
        return concurrent


def _legacy_outstanding_generation(
    session: Session,
    *,
    normalized: str,
    word_idx: int,
    source_note_id: str | None,
) -> GenerationJob | None:
    candidates = session.scalars(
        select(GenerationJob).where(
            GenerationJob.source_note_id == source_note_id,
            GenerationJob.provider_config["word_idx"].as_integer() == word_idx,
            or_(
                GenerationJob.status.in_(("pending", "running")),
                GenerationJob.draft.has(Draft.status == "editable"),
            ),
        )
    )
    return next(
        (item for item in candidates if normalize_english_word(item.input_word) == normalized),
        None,
    )
