#!/usr/bin/env bash
# Destructive operator reset of a stopped, reconciled installation.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
source "$NACHTLABS_ROOT/scripts/maintenance-common.sh"

step() { printf '\n== %s ==\n' "$1"; }
die() { printf 'Refusing to continue: %s\n' "$1" >&2; exit 1; }
UNITS=(nachtlabs-api nachtlabs-worker nachtlabs-web)
RESET_ARGS=()
case "${1:-}" in
  --force) RESET_ARGS=(--force) ;;
  '') ;;
  *) die "usage: reset-first-run.sh [--force]" ;;
esac

step "Preflight"
[[ "$NACHTLABS_ROOT" == /opt/nachtlabs && "$EUID" -eq 0 ]] || die "run as root at /opt/nachtlabs"
tree_status="$(git status --porcelain)" || die "cannot inspect the working tree"
[[ -z "$tree_status" ]] || die "the working tree is dirty"
lock_maintenance
[[ ! -e /var/lib/nachtlabs-maintenance/update-pending ]] || die "recover the interrupted update first"
for unit in "${UNITS[@]}"; do require_unit "$unit"; done
lock_stopped_executor
ROOT_PYTHON="$NACHTLABS_ROOT/.venv/bin/python"
[[ -x "$ROOT_PYTHON" ]] || die "the installed Python environment is missing"
require_build_toolchain
[[ -r /etc/nachtlabs/migration.env ]] || die "migration.env is not readable"
set -a
source /etc/nachtlabs/migration.env
set +a

step "What is currently stored"
"$ROOT_PYTHON" scripts/maintenance_db.py inspect "${RESET_ARGS[@]}"
printf '\nThis permanently deletes all database rows and rebuilds the web application.\n'
printf 'Credentials and executor files are preserved. Type RESET to continue: '
read -r reply
[[ "$reply" == RESET ]] || die "cancelled"

phase=stopping
on_exit() {
  local code=$?
  if [[ "$code" -ne 0 && "$phase" != complete ]]; then
    if [[ "$phase" == startup ]]; then
      if ! systemctl stop "${UNITS[@]}"; then
        printf 'Service shutdown failed; inspect and stop remaining processes.\n' >&2
      fi
    fi
    printf '\nReset failed during %s. Do not resume use until recovery is complete.\n' "$phase" >&2
    printf 'Inspect the database, reapply migrations and grants if needed, then rebuild and health-check before restarting.\n' >&2
  fi
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
step "Stopping services"
systemctl stop "${UNITS[@]}"
require_stopped "${UNITS[@]}" nachtlabs-executor

phase=database-reset
step "Emptying the database"
"$ROOT_PYTHON" scripts/maintenance_db.py reset "${RESET_ARGS[@]}"
phase=migrations
"$ROOT_PYTHON" -m alembic -c apps/api/alembic.ini upgrade head
phase=permissions
"$ROOT_PYTHON" scripts/maintenance_db.py grants
"$ROOT_PYTHON" scripts/maintenance_db.py check-migrations

phase=build
# This is a fixed path below the verified installation root.
rm -rf -- "$NACHTLABS_ROOT/apps/web/.next"
bash scripts/build.sh
phase=startup
systemctl start "${UNITS[@]}"
sleep 2
bash scripts/healthcheck.sh
phase=complete
printf '\nReset complete. Open the configured origin in a private window to create the first Owner.\n'
