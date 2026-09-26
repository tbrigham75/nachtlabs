#!/usr/bin/env bash
set -euo pipefail
NACHTLABS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$NACHTLABS_ROOT"
if [[ "$(uname -s)" != Linux ]]; then
  echo 'These operator-run commands require Linux.' >&2
  exit 1
fi
load_env() {
  local env_path="${NACHTLABS_ENV_FILE:-$NACHTLABS_ROOT/.env}"
  if [[ ! -f "$env_path" ]]; then echo "Missing trusted configuration file: $env_path" >&2; exit 1; fi
  # Only source an operator-owned configuration file, never repository/request input.
  set -a
  source "$env_path"
  set +a
}

# Prove the web application can be rebuilt before anything destructive happens.
#
# Both update.sh and reset-first-run.sh stop the services and delete apps/web/.next
# and only then run the build. If node or pnpm is missing from the invoking
# account's PATH -- likely, since the services run as their own users and the
# toolchain usually lives in an operator's home directory -- the build fails
# after the old bundle is already gone, leaving a stopped service and no web
# interface at all. Call this first, while the previous state is still intact.
require_build_toolchain() {
  local missing=0 found
  for tool in node pnpm uv; do
    if ! command -v "$tool" >/dev/null; then
      printf '%s is not on PATH.\n' "$tool" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    printf '\nThe build toolchain is incomplete, so the web application cannot be\n' >&2
    printf 'rebuilt. Nothing has been changed. Install the documented Node 24 and\n' >&2
    printf 'pnpm 10, or run this from a shell whose PATH includes them.\n' >&2
    return 1
  fi
  local node_major pnpm_major
  node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  pnpm_major="$(pnpm -v 2>/dev/null | cut -d. -f1 || echo 0)"
  if [[ "$node_major" != "24" ]]; then
    printf 'Node 24 is required to build, found %s. Nothing has been changed.\n' "$node_major" >&2
    return 1
  fi
  if [[ "$pnpm_major" != "10" ]]; then
    printf 'pnpm 10 is required to build, found %s. Nothing has been changed.\n' "$pnpm_major" >&2
    return 1
  fi
  found="$(command -v node) $(command -v pnpm) $(command -v uv)"
  printf '  toolchain: node %s, pnpm %s, uv ok (%s)\n' "$node_major" "$pnpm_major" "$found"
}
