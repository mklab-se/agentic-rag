# Build context is the repository root: docker build -f api/Dockerfile .
FROM python:3.12.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /srv

RUN useradd --system --create-home app

# Path dependencies sit beside the project, as they do in the repository.
COPY search/pyproject.toml search/uv.lock /srv/search/
COPY search/src /srv/search/src
COPY agent_core/pyproject.toml agent_core/uv.lock /srv/agent_core/
COPY agent_core/src /srv/agent_core/src

WORKDIR /srv/api
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api/app ./app
RUN uv sync --frozen --no-dev && chown -R app:app /srv

USER app
EXPOSE 8000
CMD ["/srv/api/.venv/bin/uvicorn", "--factory", "app.main:build_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
