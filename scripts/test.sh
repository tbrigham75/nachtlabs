#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
case "${1:-unit}" in
 unit) uv run --no-sync pytest -m 'not integration'; pnpm test ;;
 integration) : "${NACHTLABS_TEST_DATABASE_URL_FILE:?Provide a dedicated test-database credential file}"; uv run --no-sync pytest -m integration ;;
 e2e) : "${NACHTLABS_E2E_URL:?Provide the already-running isolated test installation URL}"; pnpm test:e2e ;;
 *) echo 'Use unit, integration, or e2e' >&2; exit 1 ;;
esac
