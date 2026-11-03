# Build context is the repository root:
#   az acr build -r <registry> -t voltrieve/hosted:<tag> --platform linux/amd64 -f agents/hosted/Dockerfile .
FROM python:3.12.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1

WORKDIR /srv

RUN useradd --system --create-home app

# Path dependencies sit beside the project, as they do in the repository.
COPY search/pyproject.toml search/uv.lock /srv/search/
COPY search/src /srv/search/src
COPY agent_core/pyproject.toml agent_core/uv.lock /srv/agent_core/
COPY agent_core/src /srv/agent_core/src

WORKDIR /srv/agents/hosted
COPY agents/hosted/pyproject.toml agents/hosted/uv.lock ./
RUN uv sync --frozen --no-dev

COPY agents/hosted/main.py ./
RUN chown -R app:app /srv

USER app
EXPOSE 8088
CMD ["/srv/agents/hosted/.venv/bin/python", "main.py"]
