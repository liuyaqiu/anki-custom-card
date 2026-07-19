#!/bin/sh
set -eu

uv run --no-sync alembic upgrade head
exec uv run --no-sync uvicorn anki_custom_card.app:app --host 0.0.0.0 --port 8000

