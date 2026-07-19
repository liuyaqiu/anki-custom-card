from typing import Any, Literal

from pydantic import BaseModel, Field

NoteDomain = Literal["general", "workplace", "it"]


class NoteCreate(BaseModel):
    language: str = "en"
    word_display: str
    word_idx: int = Field(default=0, ge=0)
    variant: str | None = None
    domain: NoteDomain = "general"
    part_of_speech: str | None = None
    source_sense_ids: list[str] = Field(default_factory=list)
    definition_en: str
    definition_zh: str
    example: str
    example_zh: str
    pronunciation: str | None = None
    collocations: list[dict[str, Any]] = Field(default_factory=list)
    usage_notes: str | None = None
    extra: str | None = None


class NoteUpdate(BaseModel):
    variant: str | None = None
    domain: NoteDomain | None = None
    part_of_speech: str | None = None
    source_sense_ids: list[str] | None = None
    definition_en: str | None = None
    definition_zh: str | None = None
    example: str | None = None
    example_zh: str | None = None
    pronunciation: str | None = None
    collocations: list[dict[str, Any]] | None = None
    usage_notes: str | None = None
    extra: str | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
