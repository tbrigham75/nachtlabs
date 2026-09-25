#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
uv run --no-sync ruff check packages/core apps/api apps/worker tests scripts
pnpm lint
