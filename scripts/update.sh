#!/usr/bin/env bash
# Routine operator update of an installed NachtLabs release.
#
# install-systemd.sh deliberately does not build, so `git pull` alone changes
# nothing an operator can see. This performs the whole sequence in order and
# refuses to start from an unsafe state.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

ASSUME_YES=0
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=1

UNITS=(nachtlabs-api nachtlabs-worker nachtlabs-web)
have_systemd=0
if command -v systemctl >/dev/null && systemctl list-unit-files nachtlabs-api.service >/dev/null 2>&1; then
  have_systemd=1
fi

step() { printf '\n== %s ==\n' "$1"; }
die() { printf 'Refusing to continue: %s\n' "$1" >&2; exit 1; }

# --- guards -----------------------------------------------------------------

step "Preflight"
printf 'current commit : %s\n' "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'branch         : %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"

# Local edits inside the installed source are never discarded by an update.
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  printf '\nUncommitted local changes:\n'
  git status --short
  die "the working tree is dirty; commit, stash or discard them first (an update will not clobber local edits)"
fi

if [[ "$have_systemd" -eq 0 ]]; then
  die "no systemd unit for nachtlabs-api.service was found; this target is for installed deployments, not a development checkout"
fi

# An executor job mid-flight may be holding uncommitted candidate state.
if [[ -S /var/run/nachtlabs-executor/broker.sock ]] || pgrep -f "nachtlabs.execution.broker" >/dev/null 2>&1; then
  die "an executor broker is running; stop and reconcile it before updating (see docs/operations/upgrade-and-recovery.md)"
fi

for unit in "${UNITS[@]}"; do
  printf 'service %-22s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || echo unknown)"
done

if [[ "$ASSUME_YES" -eq 0 ]]; then
  printf '\nThis will stop %s, pull, rebuild, and restart them.\n' "${UNITS[*]}"
  read -r -p 'Type yes to continue: ' reply
  [[ "$reply" == "yes" ]] || die "cancelled"
fi

# --- update -----------------------------------------------------------------

step "Stopping services"
systemctl stop "${UNITS[@]}" 2>/dev/null || true
sleep 1

step "Fetching the target revision"
git fetch --all --tags
before="$(git rev-parse HEAD)"
git pull --ff-only
after="$(git rev-parse HEAD)"
if [[ "$before" == "$after" ]]; then
  printf 'Already up to date at %s. Rebuilding anyway so the bundle matches the source.\n' "$after"
else
  printf 'Advanced %s..%s\n' "$(git rev-parse --short "$before")" "$(git rev-parse --short "$after")"
fi

step "Resolving dependencies"
# --locked proves the committed lockfiles still describe a resolvable tree.
uv sync --locked --all-packages
pnpm install --frozen-lockfile

step "Building"
# scripts/build.sh, not a bare `pnpm build`: the standalone output does not
# contain .next/static unless it is copied, and the web unit serves from there.
bash scripts/build.sh

step "Checking for a pending migration"
# Compare the applied revision with the repository head. Only a new revision
# justifies touching the database during an otherwise code-only update.
revisions="$(git diff --name-only "$before" "$after" -- apps/api/migrations/versions 2>/dev/null || true)"
if [[ -n "$revisions" ]]; then
  printf 'Migration changes in this range:\n%s\n\n' "$revisions"
  printf '%s\n' 'Review the new revision, then apply it with migrator credentials:'
  printf '  %s\n' '  sudo -u nachtlabs_migrator make migrate'
  die "apply the migration deliberately; this update will not modify the database for you"
fi
printf 'No migration changes in this range.\n'

step "Starting services"
systemctl start "${UNITS[@]}"

step "Health"
sleep 2
failed=0
for unit in "${UNITS[@]}"; do
  state="$(systemctl is-active "$unit" 2>/dev/null || echo failed)"
  printf 'service %-22s %s\n' "$unit" "$state"
  [[ "$state" == "active" ]] || failed=1
done
if [[ "$failed" -ne 0 ]]; then
  printf '\nA service is not active. Check:\n  journalctl -u nachtlabs-api -n 50 --no-pager\n' >&2
  exit 1
fi
bash scripts/healthcheck.sh

printf '\nUpdate complete. Verify the first-run path with:\n  make diagnose-setup\n'
