#!/usr/bin/env bash
# Return an installed deployment to pristine pre-first-run state.
#
# Destroys the database contents and the web build, then re-migrates and rebuilds
# so the next page load must offer Owner setup. Credentials, the master key and
# every service env file under /etc/nachtlabs are left untouched, so
# configure.py does not need to run again and no secret is rotated.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1
UNITS=(nachtlabs-api nachtlabs-worker nachtlabs-web)
PGHOST=127.0.0.1
PGPORT=5432

step() { printf '\n== %s ==\n' "$1"; }
die()  { printf 'Refusing to continue: %s\n' "$1" >&2; exit 1; }

step "Preflight"
[[ "$NACHTLABS_ROOT" == "/opt/nachtlabs" ]] || die "this target resets an installed deployment at /opt/nachtlabs, not '$NACHTLABS_ROOT'"
[[ "$(id -u)" -eq 0 ]] || die "root is required to drop the database schema"
[[ -n "$(git status --porcelain 2>/dev/null)" ]] && {
  git status --short
  die "the working tree is dirty; commit, stash or discard local edits first"
}
command -v systemctl >/dev/null || die "systemctl not found; this is an installed deployment only"
systemctl list-unit-files nachtlabs-api.service >/dev/null 2>&1 || die "no nachtlabs-api.service unit found"

# The migrator owns the schema, so reuse its credential rather than inventing one.
MIGRATION_ENV=/etc/nachtlabs/migration.env
[[ -r "$MIGRATION_ENV" ]] || die "cannot read $MIGRATION_ENV; run as an account that can read it"
# shellcheck disable=SC1090
set -a; source "$MIGRATION_ENV"; set +a
CRED="${NACHTLABS_MIGRATION_DATABASE_URL_FILE:-}"
[[ -r "$CRED" ]] || die "migration credential file '$CRED' is not readable"
URL="$(cat "$CRED")"

PSQL=(/usr/bin/psql -v ON_ERROR_STOP=1 -q)
# psycopg is always present; use it when psql is not installed.
if ! command -v /usr/bin/psql >/dev/null 2>&1 && ! command -v psql >/dev/null 2>&1; then
  PY=1
else
  PY=0
  command -v psql >/dev/null 2>&1 || PSQL=()
fi

count() {
  local sql="$1"
  if [[ "${PY:-0}" == "1" ]]; then
    "$ROOT/.venv/bin/python" - "$URL" "$sql" <<'PY'
import sys
import psycopg
with psycopg.connect(sys.argv[1].replace("postgresql+psycopg://", "postgresql://")) as db:
    print(db.execute(sys.argv[2]).fetchone()[0])
PY
  else
    "${PSQL[@]}" "$URL" -tAc "$sql"
  fi
}

step "What is currently stored"
# Every one of these is destroyed below.
ORG=$(count "SELECT count(*) FROM organizations" 2>/dev/null || echo 0)
USERS=$(count "SELECT count(*) FROM users" 2>/dev/null || echo 0)
RUNS=$(count "SELECT count(*) FROM runs" 2>/dev/null || echo 0)
EVID=$(count "SELECT count(*) FROM run_evidence" 2>/dev/null || echo 0)
AUDIT=$(count "SELECT count(*) FROM audit_events" 2>/dev/null || echo 0)
INVITES=$(count "SELECT count(*) FROM identity_tokens" 2>/dev/null || echo 0)
INTEG=$(count "SELECT count(*) FROM integration_connections" 2>/dev/null || echo 0)
printf '  organizations        : %s\n  users                : %s\n  runs                 : %s\n  run evidence          : %s\n  audit events          : %s\n  identity tokens       : %s\n  integration connections: %s\n' \
  "$ORG" "$USERS" "$RUNS" "$EVID" "$AUDIT" "$INVITES" "$INTEG"

if [[ "$FORCE" -eq 0 && ( "$RUNS" != "0" || "$EVID" != "0" || "$INTEG" != "0" || "$AUDIT" -gt 2 ) ]]; then
  printf '\nThis installation has recorded activity beyond a first account.\n' >&2
  die "re-run with --force to discard runs, evidence, integrations and audit history"
fi

printf '\nThis permanently deletes every row in the database and the entire web build.\n'
printf 'It does NOT touch /etc/nachtlabs: credentials, the master key and all\n'
printf 'service env files are preserved, so no secret is rotated.\n'
printf '\nType RESET to continue: '
read -r reply
[[ "$reply" == "RESET" ]] || die "cancelled"

step "Stopping services"
systemctl stop "${UNITS[@]}" 2>/dev/null || true
if systemctl is-active --quiet nachtlabs-executor 2>/dev/null; then
  printf '%s\n' "WARNING: the executor is still running; stop it and reconcile before using it." >&2
fi
sleep 1

step "Emptying the database"
if [[ "${PY:-0}" == "1" ]]; then
  "$ROOT/.venv/bin/python" - "$URL" <<'PY'
import sys
import psycopg
with psycopg.connect(sys.argv[1].replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as db:
    db.execute("DROP SCHEMA public CASCADE")
    db.execute("CREATE SCHEMA public")
print("  schema emptied")
PY
else
  "${PSQL[@]}" "$URL" -c 'DROP SCHEMA public CASCADE' -c 'CREATE SCHEMA public'
  printf '  schema emptied\n'
fi

step "Re-applying migrations"
uv run --no-sync alembic -c apps/api/alembic.ini upgrade head >/dev/null
printf '  schema at %s\n' "$(count "SELECT version_num FROM alembic_version")"

step "Discarding the web build"
# Removing .next guarantees nothing stale can be served, which is the single
# most common reason a first-run page appears not to update.
rm -rf apps/web/.next
printf '  removed apps/web/.next\n'

step "Rebuilding"
bash scripts/build.sh >/dev/null
printf '  built\n'

step "Starting services"
systemctl start "${UNITS[@]}"
sleep 2
failed=0
for unit in "${UNITS[@]}"; do
  state="$(systemctl is-active "$unit" 2>/dev/null | head -1 || echo failed)"
  printf '  %-22s %s\n' "$unit" "$state"
  [[ "$state" == "active" ]] || failed=1
done
[[ "$failed" -eq 0 ]] || die "a service is not active; check journalctl -u nachtlabs-api -n 50"

printf '\nReset complete. This installation is now at zero accounts.\n'
printf '  1. make diagnose-setup   (confirms the bundle is current and the origin is accepted)\n'
printf '  2. open the origin in a private window\n'
printf '  3. you must see "Initialize NachtLabs"; enter an email and the password twice\n'
