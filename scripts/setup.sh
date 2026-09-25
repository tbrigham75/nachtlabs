#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
command -v uv >/dev/null
command -v pnpm >/dev/null
# systemd ProtectHome must not depend on a uv-managed interpreter in a home directory.
export UV_PYTHON=/usr/bin/python3.12
export UV_NO_MANAGED_PYTHON=1
[[ -x "$UV_PYTHON" ]] || { printf '%s\n' 'Install system Python 3.12 first.' >&2; exit 1; }
install -d apps/web/public/docs-assets
# Dependency resolution is deliberately deferred to this operator-run handoff.
if [[ -f uv.lock ]]; then uv sync --locked --all-packages; else uv lock && uv sync --locked --all-packages; fi
if [[ -f pnpm-lock.yaml ]]; then pnpm install --frozen-lockfile; else pnpm install; fi
cp node_modules/swagger-ui-dist/swagger-ui-bundle.js node_modules/swagger-ui-dist/swagger-ui.css node_modules/swagger-ui-dist/favicon-32x32.png apps/web/public/docs-assets/
printf '%s\n' 'Dependencies resolved. Retain both lockfiles with this handoff before subsequent installations.'
