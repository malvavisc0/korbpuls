#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
RELOAD="${RELOAD:-false}"
RUNNER="${RUNNER-uv run}"

ARGS=(
    --host "$HOST"
    --port "$PORT"
)

if [ "$RELOAD" = "true" ]; then
    ARGS+=(--reload)
else
    ARGS+=(--workers "$WORKERS")
fi

exec $RUNNER uvicorn korbpuls.main:app "${ARGS[@]}" "$@"
