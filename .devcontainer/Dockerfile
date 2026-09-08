# syntax=docker/dockerfile:1.7
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm@sha256:7876580dc67fd460fd962f004cbeb480027e9bbc0657096f1087db11f9eaff39

# The base image ships a yarn apt source whose signing key no longer verifies and
# this project has no Node toolchain, so drop it before touching apt.
# espeak-ng and ffmpeg back scripts/generate_test_fixture.sh.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends espeak-ng ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Same pinned uv as the runtime image, so lockfile resolution matches CI.
COPY --from=ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 \
     /uv /uvx /usr/local/bin/

# Default to the unprivileged user that devcontainer.json also selects as remoteUser.
# Features are still installed as root: the dev container CLI re-elevates around them.
USER vscode
