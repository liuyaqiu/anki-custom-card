# syntax=docker/dockerfile:1.7

FROM python:3.12.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY --chmod=755 docker/entrypoint.sh /app/docker/entrypoint.sh

FROM base AS test

COPY tests ./tests
RUN uv sync --locked

CMD ["uv", "run", "pytest"]

FROM base AS runtime

RUN uv sync --locked --no-dev && \
    groupadd --system app && \
    useradd --system --gid app --home-dir /app app && \
    mkdir -p /app/data && \
    chown -R app:app /app

USER app

EXPOSE 8000

CMD ["/app/docker/entrypoint.sh"]
