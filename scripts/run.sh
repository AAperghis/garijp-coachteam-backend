#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Load dev env vars if the file exists and is non-empty
if [ -s .env.dev ]; then
  set -a
  source .env.dev
  set +a
fi

PORT="${BACKEND_PORT:-8000}"

PYTHONPATH="$REPO_ROOT/src" exec uvicorn main:app \
  --reload \
  --host 0.0.0.0 \
  --port "$PORT"
