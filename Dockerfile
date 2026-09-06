# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /nonexistent app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/config /app/config
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
CMD ["open-transcribe-mcp"]
