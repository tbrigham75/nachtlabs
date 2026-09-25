#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
uv run --no-sync uvicorn nachtlabs_api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --log-config config/logging.json & api_pid=$!
uv run --no-sync python -m nachtlabs_worker.main & worker_pid=$!
pnpm dev & web_pid=$!
cleanup() { kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait -n "$api_pid" "$worker_pid" "$web_pid"
