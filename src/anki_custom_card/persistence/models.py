from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class Note(TimestampMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint(
            "language", "word_normalized", "word_idx", name="uq_notes_business_identity"
        ),
        CheckConstraint("word_idx >= 0", name="ck_notes_word_idx_nonnegative"),
        CheckConstraint("version >= 1", name="ck_notes_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    word_display: Mapped[str] = mapped_column(String(512), nullable=False)
    word_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    word_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    variant: Mapped[str | None] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    part_of_speech: Mapped[str | None] = mapped_column(String(64))
    source_sense_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    definition_en: Mapped[str] = mapped_column(Text, nullable=False)
    definition_zh: Mapped[str] = mapped_column(Text, nullable=False)
    example: Mapped[str] = mapped_column(Text, nullable=False)
    example_zh: Mapped[str] = mapped_column(Text, nullable=False)
    pronunciation: Mapped[str | None] = mapped_column(String(256))
    collocations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    usage_notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    revisions: Mapped[list[NoteRevision]] = relationship(
        back_populates="note", cascade="all, delete-orphan", passive_deletes=True
    )
    generation_jobs: Mapped[list[GenerationJob]] = relationship(
        back_populates="source_note", cascade="all, delete-orphan", passive_deletes=True
    )
    media_links: Mapped[list[NoteMedia]] = relationship(
        back_populates="note", cascade="all, delete-orphan", passive_deletes=True
    )
    publication: Mapped[AnkiPublication | None] = relationship(
        back_populates="note", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class NoteRevision(Base):
    __tablename__ = "note_revisions"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_note_revisions_version_positive"),)

    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )

    note: Mapped[Note] = relationship(back_populates="revisions")


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (UniqueConstraint("request_key", name="uq_generation_jobs_request_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    input_word: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    request_key: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    provider_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_note: Mapped[Note | None] = relationship(back_populates="generation_jobs")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="generation_job", cascade="all, delete-orphan", passive_deletes=True
    )
    draft: Mapped[Draft | None] = relationship(
        back_populates="generation_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class DictionaryCacheEntry(Base):
    __tablename__ = "dictionary_cache_entries"
    __table_args__ = (
        UniqueConstraint("provider", "request_key", name="uq_dictionary_cache_provider_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_dataset: Mapped[str | None] = mapped_column(String(128))
    provider_config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_query: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    artifacts: Mapped[list[Artifact]] = relationship(back_populates="dictionary_cache")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    generation_job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dictionary_cache_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "dictionary_cache_entries.id",
            name="fk_artifacts_dictionary_cache_id",
            ondelete="SET NULL",
        ),
        index=True,
    )
    media_id: Mapped[str | None] = mapped_column(
        ForeignKey("media.id", name="fk_artifacts_media_id", ondelete="SET NULL"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_response_id: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    structured_content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )

    generation_job: Mapped[GenerationJob] = relationship(back_populates="artifacts")
    dictionary_cache: Mapped[DictionaryCacheEntry | None] = relationship(back_populates="artifacts")
    media: Mapped[Media | None] = relationship(back_populates="artifacts")


class Draft(TimestampMixin, Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    generation_job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="editable", server_default="editable", nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    confirmed_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("notes.id", name="fk_drafts_confirmed_note_id", ondelete="SET NULL")
    )

    generation_job: Mapped[GenerationJob] = relationship(back_populates="draft")


class Media(Base):
    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )

    links: Mapped[list[NoteMedia]] = relationship(
        back_populates="media", cascade="all, delete-orphan", passive_deletes=True
    )
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="media")
    speech_cache_entries: Mapped[list[SpeechCacheEntry]] = relationship(back_populates="media")


class SpeechCacheEntry(Base):
    __tablename__ = "speech_cache_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    voice: Mapped[str] = mapped_column(String(128), nullable=False)
    ssml: Mapped[str] = mapped_column(Text, nullable=False)
    output_format: Mapped[str] = mapped_column(String(128), nullable=False)
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", name="fk_speech_cache_media_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )

    media: Mapped[Media] = relationship(back_populates="speech_cache_entries")


class NoteMedia(Base):
    __tablename__ = "note_media"

    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    usage: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True
    )

    note: Mapped[Note] = relationship(back_populates="media_links")
    media: Mapped[Media] = relationship(back_populates="links")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts_positive"),
        Index(
            "uq_jobs_active_aggregate",
            "job_type",
            "aggregate_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_jobs_claim", "status", "available_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class AnkiPublication(Base):
    __tablename__ = "anki_publications"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_anki_publications_attempt_nonnegative"),
    )

    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    anki_note_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    target_deck: Mapped[str] = mapped_column(String(256), nullable=False)
    target_note_type: Mapped[str] = mapped_column(String(256), nullable=False)
    published_version: Mapped[int | None] = mapped_column(Integer)
    publishing_version: Mapped[int | None] = mapped_column(Integer)
    published_hash: Mapped[str | None] = mapped_column(String(64))
    observed_anki_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    note: Mapped[Note] = relationship(back_populates="publication")
