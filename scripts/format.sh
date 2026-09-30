#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
if [[ "${1:-check}" == write ]]; then
 uv run --no-sync ruff check --select I --fix packages/core apps/api apps/worker tests scripts
 uv run --no-sync ruff format packages/core apps/api apps/worker tests scripts
 pnpm exec prettier --write apps/web packages/api-client packages/mcp-server tests/e2e
else
 uv run --no-sync ruff format --check packages/core apps/api apps/worker tests scripts
 pnpm format:check
fi
