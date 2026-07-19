import base64
from typing import Any

import httpx


class AnkiConnectError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AnkiConnectClient:
    def __init__(self, url: str, *, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.url = url
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def invoke(self, action: str, **params: object) -> Any:
        try:
            response = await self._client.post(
                self.url, json={"action": action, "version": 6, "params": params}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AnkiConnectError("anki_unavailable", str(error), retryable=True) from error
        if not isinstance(payload, dict) or set(payload) != {"result", "error"}:
            raise AnkiConnectError(
                "anki_invalid_response", "AnkiConnect returned an invalid envelope", retryable=False
            )
        if payload["error"] is not None:
            raise AnkiConnectError("anki_action_failed", str(payload["error"]), retryable=False)
        return payload["result"]

    async def deck_names(self) -> list[str]:
        return list(await self.invoke("deckNames"))

    async def version(self) -> int:
        return int(await self.invoke("version"))

    async def create_deck(self, name: str) -> int:
        return int(await self.invoke("createDeck", deck=name))

    async def model_names(self) -> list[str]:
        return list(await self.invoke("modelNames"))

    async def model_field_names(self, name: str) -> list[str]:
        return list(await self.invoke("modelFieldNames", modelName=name))

    async def create_model(
        self, *, name: str, fields: list[str], css: str, templates: list[dict[str, str]]
    ) -> object:
        return await self.invoke(
            "createModel",
            modelName=name,
            inOrderFields=fields,
            css=css,
            cardTemplates=templates,
        )

    async def update_model_templates(self, name: str, templates: list[dict[str, str]]) -> None:
        await self.invoke(
            "updateModelTemplates",
            model={
                "name": name,
                "templates": {
                    item["Name"]: {"Front": item["Front"], "Back": item["Back"]}
                    for item in templates
                },
            },
        )

    async def update_model_styling(self, name: str, css: str) -> None:
        await self.invoke("updateModelStyling", model={"name": name, "css": css})

    async def store_media(self, *, filename: str, content: bytes) -> str:
        encoded = base64.b64encode(content).decode("ascii")
        return str(await self.invoke("storeMediaFile", filename=filename, data=encoded))

    async def find_notes(self, query: str) -> list[int]:
        return [int(value) for value in await self.invoke("findNotes", query=query)]

    async def add_note(
        self, *, deck: str, model: str, fields: dict[str, str], tags: list[str]
    ) -> int:
        note = {"deckName": deck, "modelName": model, "fields": fields, "tags": tags}
        return int(await self.invoke("addNote", note=note))

    async def update_note(self, note_id: int, *, fields: dict[str, str], tags: list[str]) -> None:
        await self.invoke("updateNoteFields", note={"id": note_id, "fields": fields})
        await self.invoke("addTags", notes=[note_id], tags=" ".join(tags))

    async def notes_info(self, note_ids: list[int]) -> list[dict[str, Any]]:
        # AnkiConnect preserves positional correspondence by returning an empty
        # object for a missing Note. Do not expose those placeholders as
        # existing Notes to publication and deletion confirmation logic.
        result = await self.invoke("notesInfo", notes=note_ids)
        return [item for item in result if isinstance(item, dict) and "noteId" in item]

    async def delete_notes(self, note_ids: list[int]) -> None:
        await self.invoke("deleteNotes", notes=note_ids)
