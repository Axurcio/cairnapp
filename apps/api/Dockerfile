# syntax=docker/dockerfile:1.7
# One image, several process types (modular monolith): the API, the Temporal
# worker and the migration job all run from this image with different commands.
# Build context: repository root.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Optional extras, e.g. --build-arg CAIRN_EXTRAS=nemo
ARG CAIRN_EXTRAS=""
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
      $(for e in ${CAIRN_EXTRAS}; do printf -- '--extra %s ' "$e"; done)

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    GRAPHITI_TELEMETRY_ENABLED=false
RUN groupadd --system --gid 10001 cairn \
 && useradd --system --uid 10001 --gid cairn --home-dir /app --no-create-home cairn
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=cairn:cairn cairn ./cairn
COPY --chown=cairn:cairn domain_packs ./domain_packs
COPY --chown=cairn:cairn migrations ./migrations
COPY --chown=cairn:cairn scripts ./scripts
COPY --chown=cairn:cairn alembic.ini pyproject.toml ./
USER cairn
EXPOSE 8000
CMD ["uvicorn", "cairn.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
