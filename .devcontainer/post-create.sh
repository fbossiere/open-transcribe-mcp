#!/usr/bin/env bash
set -euo pipefail

cache_dir="${UV_CACHE_DIR:-$HOME/.cache/uv}"
if [ ! -w "$cache_dir" ]; then
  # Named volumes are created root-owned on first boot.
  sudo chown -R "$(id -u):$(id -g)" "$cache_dir"
fi

echo "Syncing locked dependencies (dev + s3)..."
uv sync --locked --extra dev --extra s3

# No .env is generated on purpose: Settings reads .env from the working directory,
# so an unrequested one would silently become an input to the test suite.
if [ ! -f .env ]; then
  echo "No .env present. To run the server locally: cp .env.example .env, then fill in credentials."
fi
