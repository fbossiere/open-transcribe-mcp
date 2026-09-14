# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 AS uv

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS base
# Apply Debian fixes published since the pinned Python image was built.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra s3 --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev --extra s3 --no-editable

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/fbossiere/open-transcribe-mcp" \
      org.opencontainers.image.title="OpenTranscribe MCP" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /nonexistent app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/config /app/config
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
CMD ["open-transcribe-mcp"]
