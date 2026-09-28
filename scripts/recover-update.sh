#!/usr/bin/env bash
# Run the saved copy through /var/lib/nachtlabs-maintenance/update-pending.
# It must work even when the installed Python environment or scripts are broken.
set -euo pipefail
die() { printf 'Recovery stopped: %s\n' "$1" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || die "root is required"
PENDING=/var/lib/nachtlabs-maintenance/update-pending
backup="$(realpath -e "$PENDING")" || die "no pending update"
[[ "$backup" == /var/lib/nachtlabs-maintenance/update.* ]] || die "unexpected recovery location"
[[ "$(dirname -- "$backup")" == /var/lib/nachtlabs-maintenance ]] || die "unexpected recovery parent"
source "$backup/maintenance-common.sh"
lock_maintenance
lock_stopped_executor
UNITS=(nachtlabs-api nachtlabs-worker nachtlabs-web)
cd /opt/nachtlabs
systemctl stop "${UNITS[@]}"
require_stopped "${UNITS[@]}" nachtlabs-executor
before="$(cat "$backup/source.commit")"
git cat-file -e "$before^{commit}"
if [[ -e "$backup/activation-started" ]]; then
  [[ -f "$backup/snapshot-ready" && -f "$backup/source.tar" ]] || die "no complete recovery snapshot; keep services stopped"
  # Only a clean installation was admitted. Recovery deliberately restores its
  # source and fixed runtime directories; untracked files elsewhere are retained.
  git reset --hard "$before"
  rm -rf -- /opt/nachtlabs/.venv /opt/nachtlabs/node_modules \
    /opt/nachtlabs/apps/web/node_modules /opt/nachtlabs/packages/api-client/node_modules \
    /opt/nachtlabs/apps/web/.next /opt/nachtlabs/apps/web/public/docs-assets
  tar -xpf "$backup/source.tar" -C /opt/nachtlabs
fi
# Preserve the database selected by the original update, including an explicit
# trusted environment override. Store only the credential file path, not its value.
NACHTLABS_MIGRATION_DATABASE_URL_FILE="$(cat "$backup/migration-credential-file")"
export NACHTLABS_MIGRATION_DATABASE_URL_FILE
# An operator may have changed the DB during an interruption. Never restart the
# old release unless its own revision agrees with the actual database.
/opt/nachtlabs/.venv/bin/python "$backup/maintenance_db.py" check-migrations --root /opt/nachtlabs
while IFS= read -r unit; do
  case "$unit" in
    nachtlabs-api|nachtlabs-worker|nachtlabs-web) systemctl start "$unit" ;;
    *) die "invalid saved service name" ;;
  esac
  [[ "$(systemctl show "$unit" --property=ActiveState --value)" == active ]] || die "$unit did not become active"
done < "$backup/active-units"
rm -- "$PENDING"
printf 'Previous source/runtime and service state restored. Run make healthcheck before resuming work.\n'
printf 'Recovery files remain at %s.\n' "$backup"
