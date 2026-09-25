#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
load_env
if [[ "${1:-generate}" == check ]]; then
 test -f docs/api/openapi.json && test -f packages/api-client/src/generated.d.ts
 snapshot=$(mktemp -d)
 trap 'rm -f -- "$snapshot/openapi.json" "$snapshot/generated.d.ts"; rmdir -- "$snapshot"' EXIT
 cp docs/api/openapi.json "$snapshot/openapi.json"
 cp packages/api-client/src/generated.d.ts "$snapshot/generated.d.ts"
 uv run --no-sync python -m nachtlabs_api.export_schema
 pnpm api:generate
 cmp docs/api/openapi.json "$snapshot/openapi.json"
 cmp packages/api-client/src/generated.d.ts "$snapshot/generated.d.ts"
else
 uv run --no-sync python -m nachtlabs_api.export_schema
 pnpm api:generate
fi
