#!/usr/bin/env bash
# Read-only first-run diagnosis. Changes nothing; safe to run at any time.
#
# The recurring cause of "I cannot get in" is a stale web bundle: install-systemd.sh
# does not build, so a pulled commit is never compiled. This reports that directly
# instead of leaving it to be guessed.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

bundle_stale=0
behind=0

ok()   { printf '  [ ok ]   %s\n' "$1"; }
bad()  { printf '  [ !! ]   %s\n' "$1"; }
warn() { printf '  [ ?? ]   %s\n' "$1"; }
head2() { printf '\n== %s ==\n' "$1"; }

STANDALONE=apps/web/.next/standalone/apps/web
MARKER="Create the Owner account"

head2 "Source"
if git rev-parse --git-dir >/dev/null 2>&1; then
  commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  printf '  installed commit : %s\n' "$commit"
  printf '  branch           : %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    warn "working tree is dirty; an update will refuse until this is resolved"
  else
    ok "working tree is clean"
  fi
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  if [[ -z "$upstream" ]]; then
    warn "no upstream configured; cannot tell whether this is behind the remote"
  else
    git fetch --quiet "$upstream" 2>/dev/null || true
    counts="$(git rev-list --left-right --count "HEAD...$upstream" 2>/dev/null || true)"
    if [[ -n "$counts" ]]; then
      ahead="${counts%%$'\t'*}"; behind="${counts##*$'\t'}"
      printf '  vs %-14s %s ahead, %s behind\n' "$upstream" "$ahead" "$behind"
      [[ "$behind" != "0" ]] && warn "$behind commit(s) behind $upstream; run 'make update'"
    fi
  fi
else
  warn "not a git checkout; cannot compare revisions"
fi

head2 "Web bundle"
if [[ -f "$STANDALONE/server.js" ]]; then
  ok "standalone build present ($STANDALONE/server.js)"
  if [[ -d "$STANDALONE/.next/static" ]]; then
    ok "static assets copied into the standalone tree"
  else
    bundle_stale=1
    bad "static assets MISSING; JavaScript is being served as HTML. Rebuild with 'make build', not 'pnpm build'"
  fi
  if grep -rqs "$MARKER" "$STANDALONE" 2>/dev/null; then
    ok "served bundle contains the first-run setup marker"
  else
    bundle_stale=1
    bad "served bundle does NOT contain '$MARKER'"
    bad "this build predates first-run setup; run 'make update' and reload in a private window"
  fi
else
  bundle_stale=1
  bad "no standalone build at $STANDALONE; run 'make build'"
fi

head2 "API and database"
api_url="${NACHTLABS_DIAGNOSE_API_URL:-}"
if [[ -z "$api_url" ]] && [[ -f .env ]]; then
  api_url="$(sed -n 's/^NACHTLABS_INTERNAL_API_URL=//p' .env | tr -d '"'"'" | tail -1)"
fi
api_url="${api_url:-http://127.0.0.1:8000}"
printf '  api url : %s\n' "$api_url"

# curl prints its own 000 on a connection failure, so appending a fallback would
# report "000000" and defeat the match below.
status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$api_url/api/v1/health/ready" 2>/dev/null)" || true
status="${status:-000}"
if [[ "$status" == "200" ]]; then
  ok "health/ready returned 200"
else
  bad "health/ready returned $status (is nachtlabs-api running?)"
fi

body="$(curl -s --max-time 5 "$api_url/api/v1/auth/setup-status" 2>/dev/null || true)"
if [[ -z "$body" ]]; then
  bad "could not read /auth/setup-status"
  warn "if this fails while a reverse proxy is in front, /api/ is probably not being forwarded to the API"
else
  printf '  setup-status : %s\n' "$body"
  case "$body" in
    *'"initialized":false'*) ok "no account exists; the Owner setup form should be offered" ;;
    *'"initialized":true'*)  warn "setup is already complete; use 'make recover-owner' if you have lost the credential" ;;
    *) warn "unrecognised setup-status payload" ;;
  esac
fi

if [[ -f .env ]]; then
  if grep -q '^NACHTLABS_SETUP_TOKEN_REQUIRED=true' .env 2>/dev/null; then
    warn "NACHTLABS_SETUP_TOKEN_REQUIRED=true; first-account creation also needs the one-time token"
  fi
  if grep -qE '^NACHTLABS_SMTP_HOST=(""|'"''"'|)$' .env 2>/dev/null; then
    warn "SMTP is not configured; password reset and account invitations cannot be delivered"
  fi
  # Said out loud rather than left to be discovered, because the symptom an
  # operator meets is only "the wizard refused my endpoint" and the cause is
  # four lines up in a file they may not have edited recently.
  if grep -q '^NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true' .env 2>/dev/null; then
    warn "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true; cleartext HTTP to a private provider is permitted, so model requests and model replies cross the network unprotected. A reverse proxy in front of a loopback provider keeps the same traffic off the wire."
  fi
fi

head2 "Origin check (why a form can look dead)"
# A GET never reaches browser_origin, and a mutating endpoint rejects an invalid
# body during validation before that check runs. So the only honest way to ask
# "would a POST from this browser be accepted?" is to ask the API, which is what
# /auth/preflight does. It mutates nothing.
public_url=""
for candidate in .env /etc/nachtlabs/api.env; do
  if [[ -r "$candidate" ]]; then
    public_url="$(sed -n 's/^NACHTLABS_PUBLIC_URL=//p' "$candidate" | tr -d "\"'\''" | tail -1)"
    [[ -n "$public_url" ]] && break
  fi
done
if [[ -z "$public_url" ]]; then
  warn "could not read NACHTLABS_PUBLIC_URL from .env or /etc/nachtlabs/api.env"
  warn "set NACHTLABS_DIAGNOSE_ORIGIN=https://your-host to check by hand"
else
  printf '  PUBLIC_URL : %s\n' "$public_url"
  # The canonical origin stays one value; NACHTLABS_ALLOWED_ORIGINS widens the
  # set of addresses that work, and every entry is an operator decision.
  extra_origins=""
  for candidate in .env /etc/nachtlabs/api.env; do
    if [[ -r "$candidate" ]]; then
      extra_origins="$(sed -n 's/^NACHTLABS_ALLOWED_ORIGINS=//p' "$candidate" | tr -d "\"'\''" | tail -1)"
      [[ -n "$extra_origins" ]] && break
    fi
  done
  if [[ -n "$extra_origins" ]]; then
    printf '  also permitted : %s\n' "$extra_origins"
  fi
  # Always reach the configured origin, but send whichever origin the browser
  # would send. Setting NACHTLABS_DIAGNOSE_ORIGIN to the address you actually
  # type into the browser reproduces a host mismatch exactly.
  browser_origin="${NACHTLABS_DIAGNOSE_ORIGIN:-$public_url}"
  if [[ "$browser_origin" != "$public_url" ]]; then
    warn "testing as browser origin $browser_origin (configured: $public_url)"
  fi
  pre="$(curl -s --max-time 8 -H "Origin: $browser_origin" "$public_url/api/v1/auth/preflight" 2>/dev/null || true)"
  if [[ -z "$pre" ]]; then
    bad "could not reach /auth/preflight at $public_url"
    bad "the reverse proxy is probably not forwarding /api/ to the API"
  else
    printf '  %s\n' "$pre"
    case "$pre" in
      *'"origin_accepted":true'*)
        ok "this origin is accepted, so creating the first account will work"
        ;;
      *'"origin_accepted":false'*)
        bad "this origin is REFUSED, so every create/sign-in POST is rejected"
        bad "add it to NACHTLABS_ALLOWED_ORIGINS, and its host to NACHTLABS_ALLOWED_HOSTS, then:"
        bad "  sudo systemctl restart nachtlabs-api nachtlabs-web"
        ;;
      *) warn "unrecognised preflight response" ;;
    esac
    case "$pre" in
      *'"setup_token_required":true'*)
        warn "first-account creation also requires the one-time setup token"
        ;;
    esac
    # Cookie security is decided by the whole set, not the canonical origin: a
    # Secure cookie is never sent over plain HTTP, so one HTTP entry is enough to
    # cost the attribute and must be reported as such.
    case "$pre" in
      *'"secure_cookies":true'*)
        ok "every permitted origin is https, so the session cookie is issued Secure"
        ;;
      *'"secure_cookies":false'*)
        warn "at least one permitted origin is plain http; the session cookie cannot be Secure"
        warn "serve every permitted origin over https to restore it"
        ;;
    esac
    # Probe every permitted origin, so a wrong entry is caught from the host
    # rather than by an operator discovering it in a browser.
    for probe_origin in $(printf '%s' "$pre" | sed -n 's/.*"allowed":\[\(.*\)\].*/\1/p' |
      tr ',' '\n' | tr -d '[]" '); do
      [[ -z "$probe_origin" ]] && continue
      result="$(curl -s --max-time 8 -H "Origin: $probe_origin" \
        "$probe_origin/api/v1/auth/preflight" 2>/dev/null || true)"
      case "$result" in
        *'"origin_accepted":true'*) ok "permitted origin answers: $probe_origin" ;;
        *)
          bad "permitted origin does NOT answer: $probe_origin"
          bad "  it is not reachable, or a proxy is not forwarding /api/ for that host"
          ;;
      esac
    done
  fi
fi

head2 "Services"
# systemctl prints its own state and still exits non-zero, so capture once and
# normalise rather than appending a second line onto the first.
unit_state() {
  local raw state
  raw="$(systemctl is-active "$1" 2>/dev/null | head -1 | tr -d '[:space:]')"
  if [[ -z "$raw" ]]; then
    raw="$(systemctl list-unit-files "$1.service" >/dev/null 2>&1 && echo unknown || echo absent)"
  fi
  printf '%s' "$raw"
}
if command -v systemctl >/dev/null 2>&1; then
  for unit in nachtlabs-api nachtlabs-worker nachtlabs-web nachtlabs-executor; do
    state="$(unit_state "$unit")"
    case "$state" in
      active)  ok "$unit is active" ;;
      absent)  warn "$unit is not installed" ;;
      unknown) warn "$unit state could not be determined" ;;
      *)       warn "$unit is $state" ;;
    esac
  done
else
  warn "systemctl unavailable; cannot report unit state"
fi

head2 "Summary"
if [[ "${bundle_stale:-0}" == "1" ]]; then
  printf '  [!] The served web bundle is stale. This is the usual cause of a missing\n'
  printf '      first-run setup form. Run "make update", then reload in a private window.\n'
elif [[ "${behind:-0}" != "0" && -n "${behind:-}" ]]; then
  printf '  [!] %s commit(s) behind the remote, bundle already current. Run "make update".\n' "$behind"
else
  printf '  Source and served bundle agree. No update is needed.\n'
fi
printf '  On a fresh installation the first load must show "Initialize NachtLabs".\n'
