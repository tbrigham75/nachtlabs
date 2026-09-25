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
