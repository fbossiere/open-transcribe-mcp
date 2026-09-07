# syntax=docker/dockerfile:1.7
FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm@sha256:b1c8e01d2dcb17a102fdd0abd2d2f4737f2b1be0373944314ef22c39f3c4b931

# The base image ships a yarn apt source whose signing key no longer verifies and
# this project has no Node toolchain, so drop it before touching apt.
# espeak-ng and ffmpeg back scripts/generate_test_fixture.sh.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends espeak-ng ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Same pinned uv as the runtime image, so lockfile resolution matches CI.
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 \
     /uv /uvx /usr/local/bin/

# Default to the unprivileged user that devcontainer.json also selects as remoteUser.
# Features are still installed as root: the dev container CLI re-elevates around them.
USER vscode
