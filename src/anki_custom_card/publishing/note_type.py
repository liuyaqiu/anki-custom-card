# ruff: noqa: E501 - embedded Anki HTML/CSS is maintained as renderable source
import re
from dataclasses import dataclass

from anki_custom_card.publishing.ports import AnkiGateway

NOTE_TYPE_NAME = "Anki Custom Card Basic v1"
NOTE_TYPE_VERSION = 4
FIELDS = [
    "SourceId",
    "Word",
    "Domain",
    "PartOfSpeech",
    "Pronunciation",
    "DefinitionEn",
    "DefinitionZh",
    "Example",
    "ExampleZh",
    "Collocations",
    "UsageNotes",
    "WordAudio",
    "ExampleAudio",
    "Extra",
]
FRONT_TEMPLATE = """<main class="acc-card acc-front">
<div class="domain">{{Domain}}</div>
<div class="word">{{Word}}</div>
<div class="meta"><span>{{PartOfSpeech}}</span><span>{{Pronunciation}}</span></div>
<div class="audio">{{WordAudio}}</div>
<section class="front-example"><div class="example">“{{Example}}”</div><div class="example-audio">{{ExampleAudio}}</div></section>
</main>"""
BACK_TEMPLATE = """<section class="acc-answer">
<div class="section definition"><div class="label">Definition</div><div class="definition-en">{{DefinitionEn}}</div><div class="definition-zh">{{DefinitionZh}}</div></div>
<div class="section example-block"><div class="label">In context</div><div class="example">“{{Example}}”</div><div class="example-zh">{{ExampleZh}}</div><div class="example-audio">{{ExampleAudio}}</div></div>
{{#Collocations}}<div class="section"><div class="label">Collocations</div><div class="chips">{{Collocations}}</div></div>{{/Collocations}}
{{#UsageNotes}}<div class="section"><div class="label">Usage</div><div class="usage">{{UsageNotes}}</div></div>{{/UsageNotes}}
{{#Extra}}<div class="section extra">{{Extra}}</div>{{/Extra}}
</section>"""
CSS = """:root { --acc-template-version: 4; }
.card { font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 19px; text-align: left; color: #172033; background: #f4f7fb; margin: 0; }
.acc-card, .acc-answer { max-width: 42rem; margin: 0 auto; padding: 1.35rem 1.5rem; }
.acc-front { min-height: calc(100vh - 2.7rem); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding-top: 1.35rem; padding-bottom: 1.35rem; }
.domain { display: inline-block; padding: .2rem .65rem; border-radius: 999px; background: #e8efff; color: #3158ad; font-size: .68rem; font-weight: 750; letter-spacing: .09em; text-transform: uppercase; }
.word { margin-top: .75rem; font-size: 2.5rem; line-height: 1.12; font-weight: 760; letter-spacing: -.025em; }
.meta { display: flex; justify-content: center; gap: .8rem; margin-top: .65rem; color: #697386; font-size: .9rem; }
.audio, .example-audio { margin-top: .75rem; text-align: center; }
.front-example { width: min(100%, 34rem); margin-top: 1.45rem; padding-top: 1.2rem; border-top: 1px solid #dbe2ec; }
.front-example .example { color: #334568; font-size: 1.05rem; font-style: normal; line-height: 1.65; }
.acc-answer { padding-top: .35rem; }
.section { margin: 1rem 0; padding: 1rem 1.05rem; border: 1px solid #e0e6ef; border-radius: 12px; background: #fff; box-shadow: 0 3px 12px rgba(23,32,51,.045); }
.label { margin-bottom: .45rem; color: #60708a; font-size: .67rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
.definition-en { font-size: 1.08rem; font-weight: 620; line-height: 1.55; }
.definition-zh, .example-zh { margin-top: .35rem; color: #667085; font-size: .88rem; line-height: 1.5; }
.example-block { border-left: 4px solid #5378da; }
.example { color: #263a69; font-size: 1.04rem; font-style: italic; line-height: 1.6; }
.chips, .usage, .extra { color: #3f4b5f; line-height: 1.55; }
.nightMode.card, .nightMode .card { color: #e8edf5; background: #121722; }
.nightMode .domain { background: #23345e; color: #b9ccff; }
.nightMode .section { background: #1b2230; border-color: #303a4c; box-shadow: none; }
.nightMode .front-example { border-color: #303a4c; }
.nightMode .meta, .nightMode .definition-zh, .nightMode .example-zh, .nightMode .label { color: #aab4c5; }
.nightMode .example, .nightMode .front-example .example { color: #c6d5ff; }"""
TEMPLATES = [{"Name": "Card 1", "Front": FRONT_TEMPLATE, "Back": BACK_TEMPLATE}]


def render_card_template(
    template: str,
    fields: dict[str, str],
    *,
    front_side: str = "",
) -> str:
    """Render the supported Anki field subset for the browser preview."""

    rendered = template.replace("{{FrontSide}}", front_side)
    for name, value in fields.items():
        pattern = re.compile(
            r"{{#" + re.escape(name) + r"}}(.*?){{/" + re.escape(name) + r"}}", re.DOTALL
        )
        rendered = pattern.sub(
            lambda match, field_value=value: match.group(1) if field_value else "", rendered
        )
    for name, value in fields.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    return rendered


def render_card_preview(fields: dict[str, str]) -> tuple[str, str]:
    front = render_card_template(FRONT_TEMPLATE, fields)
    back = render_card_template(BACK_TEMPLATE, fields)
    return front, back


class IncompatibleNoteTypeError(RuntimeError):
    pass


@dataclass(slots=True)
class NoteTypeManager:
    gateway: AnkiGateway

    async def ensure(self, deck: str) -> None:
        if deck not in await self.gateway.deck_names():
            await self.gateway.create_deck(deck)
        if NOTE_TYPE_NAME not in await self.gateway.model_names():
            await self.gateway.create_model(
                name=NOTE_TYPE_NAME, fields=FIELDS, css=CSS, templates=TEMPLATES
            )
            return
        actual = await self.gateway.model_field_names(NOTE_TYPE_NAME)
        if actual != FIELDS:
            raise IncompatibleNoteTypeError(
                f"{NOTE_TYPE_NAME} fields are incompatible: expected {FIELDS}, got {actual}"
            )
        update_templates = getattr(self.gateway, "update_model_templates", None)
        update_styling = getattr(self.gateway, "update_model_styling", None)
        if update_templates is not None and update_styling is not None:
            await update_templates(NOTE_TYPE_NAME, TEMPLATES)
            await update_styling(NOTE_TYPE_NAME, CSS)
