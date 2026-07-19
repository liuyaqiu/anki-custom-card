from typing import Any

import pytest

from anki_custom_card.publishing.note_type import (
    BACK_TEMPLATE,
    CSS,
    FIELDS,
    FRONT_TEMPLATE,
    NOTE_TYPE_NAME,
    IncompatibleNoteTypeError,
    NoteTypeManager,
    render_card_preview,
)

pytestmark = pytest.mark.unit


class Gateway:
    def __init__(self, *, fields: list[str] | None = None) -> None:
        self.decks: list[str] = []
        self.models: list[str] = [] if fields is None else [NOTE_TYPE_NAME]
        self.fields = fields
        self.created: dict[str, Any] | None = None
        self.updated_templates: list[dict[str, str]] | None = None
        self.updated_css: str | None = None

    async def deck_names(self):
        return self.decks

    async def create_deck(self, name):
        self.decks.append(name)
        return 1

    async def model_names(self):
        return self.models

    async def model_field_names(self, name):
        return self.fields

    async def create_model(self, **values):
        self.created = values
        return values

    async def update_model_templates(self, name, templates):
        self.updated_templates = templates

    async def update_model_styling(self, name, css):
        self.updated_css = css


@pytest.mark.anyio
async def test_ensure_creates_dedicated_deck_and_model() -> None:
    gateway = Gateway()
    await NoteTypeManager(gateway).ensure("Vocabulary")  # type: ignore[arg-type]
    assert gateway.decks == ["Vocabulary"]
    assert gateway.created is not None
    assert gateway.created["name"] == NOTE_TYPE_NAME
    assert gateway.created["fields"] == FIELDS


@pytest.mark.anyio
async def test_ensure_refuses_incompatible_existing_model() -> None:
    gateway = Gateway(fields=["Front", "Back"])
    with pytest.raises(IncompatibleNoteTypeError):
        await NoteTypeManager(gateway).ensure("Vocabulary")  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_ensure_upgrades_compatible_service_owned_template() -> None:
    gateway = Gateway(fields=FIELDS)
    await NoteTypeManager(gateway).ensure("Vocabulary")  # type: ignore[arg-type]
    assert gateway.updated_templates is not None
    assert gateway.updated_css == CSS


def test_back_template_has_semantic_sections_and_versioned_night_mode_style() -> None:
    assert "Definition" in BACK_TEMPLATE
    assert "In context" in BACK_TEMPLATE
    assert "{{#Collocations}}" in BACK_TEMPLATE
    assert "--acc-template-version: 4" in CSS
    assert "{{FrontSide}}" not in BACK_TEMPLATE
    assert ".nightMode" in CSS


def test_front_template_is_centered_and_shows_english_example_with_audio() -> None:
    assert "{{Example}}" in FRONT_TEMPLATE
    assert "{{ExampleAudio}}" in FRONT_TEMPLATE
    assert "{{ExampleZh}}" not in FRONT_TEMPLATE
    assert "align-items: center" in CSS
    assert "justify-content: center" in CSS


def test_browser_preview_renders_the_same_front_and_back_templates() -> None:
    fields = {name: "" for name in FIELDS}
    fields.update({"Word": "deploy", "Example": "We deploy daily.", "UsageNotes": "IT"})
    front, back = render_card_preview(fields)
    assert "deploy" in front and "We deploy daily." in front
    assert "{{" not in front
    assert front not in back
    assert "acc-front" not in back
    assert '<div class="word">deploy</div>' not in back
    assert "Usage" in back
