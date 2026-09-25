#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
if [[ "${1:-upgrade}" == check ]]; then uv run --no-sync alembic -c apps/api/alembic.ini check;
else uv run --no-sync alembic -c apps/api/alembic.ini upgrade head; fi
