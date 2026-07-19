from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmptyText = Annotated[str, Field(min_length=1)]


def reject_html(value: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError("HTML is not allowed in generated content")
    return value


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class DictionaryQuery(StrictSchema):
    word: NonEmptyText
    normalized_word: NonEmptyText
    language: NonEmptyText = "en"


class DictionaryExample(StrictSchema):
    text: NonEmptyText
    domain: str | None = None
    usage_register: str | None = Field(default=None, alias="register")


class DictionarySense(StrictSchema):
    sense_id: NonEmptyText
    definition_en: NonEmptyText
    definition_zh: str | None = None
    examples: list[DictionaryExample] = Field(default_factory=list)
    collocations: list[NonEmptyText] = Field(default_factory=list)


class DictionaryEntry(StrictSchema):
    part_of_speech: NonEmptyText
    ipa: str | None = None
    usage_register: str | None = Field(default=None, alias="register")
    domains: list[NonEmptyText] = Field(default_factory=list)
    senses: list[DictionarySense] = Field(min_length=1)


class DictionaryOutput(StrictSchema):
    schema_version: Literal[1]
    query: DictionaryQuery
    entries: list[DictionaryEntry] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_sense_ids(self) -> "DictionaryOutput":
        sense_ids = [sense.sense_id for entry in self.entries for sense in entry.senses]
        if len(sense_ids) != len(set(sense_ids)):
            raise ValueError("sense_id values must be unique")
        return self


class CardFields(StrictSchema):
    word: NonEmptyText
    domain: Literal["general", "workplace", "it"] = "general"
    part_of_speech: NonEmptyText
    ipa: str | None = None
    definition_en: NonEmptyText
    definition_zh: NonEmptyText
    example: NonEmptyText
    example_zh: NonEmptyText
    collocations: list[NonEmptyText] = Field(default_factory=list)
    usage_note: str | None = None

    @field_validator("*", mode="after")
    @classmethod
    def contain_plain_text_only(cls, value: object) -> object:
        if isinstance(value, str):
            reject_html(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    reject_html(item)
        return value


class SpeechPlan(StrictSchema):
    word_text: NonEmptyText
    example_text: NonEmptyText

    @field_validator("word_text", "example_text")
    @classmethod
    def contain_plain_text_only(cls, value: str) -> str:
        return reject_html(value)


class CardDraft(StrictSchema):
    schema_version: Literal[1]
    word: NonEmptyText
    word_idx: int = Field(ge=0)
    selected_sense_ids: list[NonEmptyText] = Field(min_length=1)
    fields: CardFields
    speech: SpeechPlan

    @field_validator("word")
    @classmethod
    def contain_plain_text_only(cls, value: str) -> str:
        return reject_html(value)
