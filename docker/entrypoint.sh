#!/bin/sh
set -eu

uv run --no-sync alembic upgrade head
exec uv run --no-sync uvicorn anki_custom_card.app:app \
  --host "${ACC_HOST:-127.0.0.1}" --port "${ACC_PORT:-8000}"
