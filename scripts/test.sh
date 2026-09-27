#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
case "${1:-unit}" in
 unit) uv run --no-sync pytest -m 'not integration'; pnpm test ;;
 integration) : "${NACHTLABS_TEST_DATABASE_URL_FILE:?Provide a dedicated test-database credential file}"; uv run --no-sync pytest -m integration ;;
 e2e)
  : "${NACHTLABS_E2E_URL:?Provide the already-running isolated test installation URL}"
  # An unprivileged host has no libnss3/libnspr4/libasound2, and Chromium then
  # fails to launch so every test fails for a reason that has nothing to do with
  # the application. This is a no-op where those libraries already resolve.
  export LD_LIBRARY_PATH="$("$(dirname -- "$0")/browser-libs.sh")"
  pnpm test:e2e
  ;;
 *) echo 'Use unit, integration, or e2e' >&2; exit 1 ;;
esac
