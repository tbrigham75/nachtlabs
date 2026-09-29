#!/usr/bin/env bash
# Prepare a release beside the live checkout, then promote it in a stopped window.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
source "$NACHTLABS_ROOT/scripts/maintenance-common.sh"

step() { printf '\n== %s ==\n' "$1"; }
die() { printf 'Refusing to continue: %s\n' "$1" >&2; exit 1; }
UNITS=(nachtlabs-api nachtlabs-worker nachtlabs-web)
ASSUME_YES=0
case "${1:-}" in
  --yes) ASSUME_YES=1 ;;
  '') ;;
  *) die "usage: update.sh [--yes]" ;;
esac

step "Preflight"
[[ "$NACHTLABS_ROOT" == /opt/nachtlabs && "$EUID" -eq 0 ]] || die "run as root at /opt/nachtlabs"
lock_maintenance
PENDING=/var/lib/nachtlabs-maintenance/update-pending
[[ ! -e "$PENDING" ]] || die "an update was interrupted; run sudo bash $PENDING/recover-update.sh"
tree_status="$(git status --porcelain)" || die "cannot inspect the working tree"
[[ -z "$tree_status" ]] || die "the working tree is dirty"
for unit in "${UNITS[@]}"; do require_unit "$unit"; done
require_build_toolchain
lock_stopped_executor
load_env
: "${NACHTLABS_MIGRATION_DATABASE_URL_FILE:?Migration credential file is required}"
ROOT_PYTHON="$NACHTLABS_ROOT/.venv/bin/python"
[[ -x "$ROOT_PYTHON" ]] || die "the installed Python environment is missing"
"$ROOT_PYTHON" scripts/maintenance_db.py reconciled
before="$(git rev-parse HEAD)"
branch="$(git symbolic-ref --short HEAD)" || die "check out the installed branch first"
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" || die "the installed branch has no upstream"

step "Fetching the target revision (services remain available)"
git fetch --all --tags
target="$(git rev-parse "$upstream^{commit}")"
git merge-base --is-ancestor "$before" "$target" || die "the update is not a fast-forward"
stage="$(mktemp -d /opt/nachtlabs-update.XXXXXXXX)"
chmod 0755 "$stage"
printf 'Preparation directory: %s\n' "$stage"
git archive "$target" | tar -x -C "$stage"
# Use the installed helper to compare the actual database with the target files.
# A pulled commit or repeated invocation cannot stand in for database state.
"$ROOT_PYTHON" scripts/maintenance_db.py check-migrations --root "$stage"

step "Preparing dependencies and web build"
# No running interpreter or bundle is modified here. Warm the Python cache too;
# the staged venv is never copied because its editable paths belong to stage.
UV_PROJECT_ENVIRONMENT="$stage/.venv" UV_PYTHON=/usr/bin/python3.12 UV_NO_MANAGED_PYTHON=1 \
  uv sync --project "$stage" --locked --all-packages
(
  cd "$stage"
  pnpm install --frozen-lockfile
  bash scripts/build.sh
)
tree_status="$(git status --porcelain)" || die "cannot inspect the working tree"
[[ "$(git rev-parse HEAD)" == "$before" && -z "$tree_status" && "$(git symbolic-ref --short HEAD)" == "$branch" ]] || die "the installed tree changed during preparation"
"$ROOT_PYTHON" scripts/maintenance_db.py check-migrations --root "$stage"
if [[ "$ASSUME_YES" -eq 0 ]]; then
  printf '\nPrepared %s. Stop services, save a recovery copy, and activate it? Type yes: ' "$target"
  read -r reply
  [[ "$reply" == yes ]] || die "cancelled; live release is unchanged"
fi
tree_status="$(git status --porcelain)" || die "cannot inspect the working tree"
[[ "$(git rev-parse HEAD)" == "$before" && -z "$tree_status" && "$(git symbolic-ref --short HEAD)" == "$branch" ]] || die "the installed tree changed while awaiting confirmation"

# A root-only recovery directory persists across SIGKILL and host restart.
# The saved recovery script does not depend on the release being activated.
backup="$(mktemp -d /var/lib/nachtlabs-maintenance/update.XXXXXXXX)"
cp scripts/recover-update.sh scripts/maintenance-common.sh scripts/maintenance_db.py "$backup/"
printf '%s\n' "$before" > "$backup/source.commit"
printf '%s\n' "$target" > "$backup/target.commit"
printf '%s\n' "$NACHTLABS_MIGRATION_DATABASE_URL_FILE" > "$backup/migration-credential-file"
: > "$backup/active-units"
for unit in "${UNITS[@]}"; do
  state="$(systemctl show "$unit" --property=ActiveState --value)"
  case "$state" in
    active) printf '%s\n' "$unit" >> "$backup/active-units" ;;
    inactive|failed) ;;
    *) die "$unit is transitioning; wait before updating" ;;
  esac
done
ln -s "$backup" "$PENDING"
sync -f "$backup"
phase=stopping
on_exit() {
  local code=$?
  if [[ "$code" -ne 0 ]]; then
    if [[ "$phase" == startup ]]; then
      if ! systemctl stop "${UNITS[@]}"; then
        printf 'Service shutdown failed; inspect and stop remaining processes before recovery.\n' >&2
      fi
    fi
    printf '\nUpdate failed during %s. Recovery data: %s\n' "$phase" "$backup" >&2
    printf 'Run: sudo bash %s/recover-update.sh\n' "$PENDING" >&2
    printf 'Do not restart the partially updated release.\n' >&2
  fi
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

step "Stopping services and saving the installed release"
systemctl stop "${UNITS[@]}"
require_stopped "${UNITS[@]}" nachtlabs-executor
"$ROOT_PYTHON" scripts/maintenance_db.py reconciled
phase=backup
# Include ignored runtime dependencies and the previous bundle, but never Git's
# object database. Services are stopped so the saved runtime is consistent.
tar --exclude='./.git' -cpf "$backup/source.tar.partial" .
mv "$backup/source.tar.partial" "$backup/source.tar"
touch "$backup/snapshot-ready"

phase=activation
# This marker is durable before the first change to installed source/runtime.
touch "$backup/activation-started"
sync -f "$backup"
git merge --ff-only "$target"
UV_PROJECT_ENVIRONMENT="$NACHTLABS_ROOT/.venv" UV_PYTHON=/usr/bin/python3.12 UV_NO_MANAGED_PYTHON=1 \
  uv sync --locked --all-packages
pnpm install --frozen-lockfile
rm -rf -- "$NACHTLABS_ROOT/apps/web/.next" "$NACHTLABS_ROOT/apps/web/public/docs-assets"
# public/ and public/docs-assets/ are gitignored, so neither is tracked in the
# archive. Recreate the parents or cp -a below fails on a tree that never built.
install -d "$NACHTLABS_ROOT/apps/web/public"
cp -a "$stage/apps/web/.next" "$NACHTLABS_ROOT/apps/web/.next"
cp -a "$stage/apps/web/public/docs-assets" "$NACHTLABS_ROOT/apps/web/public/docs-assets"
# Recheck after promotion as well; never start a release on the wrong schema.
"$ROOT_PYTHON" "$backup/maintenance_db.py" check-migrations --root "$NACHTLABS_ROOT"
phase=startup
systemctl start "${UNITS[@]}"
sleep 2
bash scripts/healthcheck.sh
phase=complete
rm -- "$PENDING"
printf '\nUpdate complete. Recovery copy retained at %s; preparation files at %s.\n' "$backup" "$stage"
