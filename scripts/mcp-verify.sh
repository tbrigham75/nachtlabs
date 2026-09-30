#!/usr/bin/env bash
# Verify a deployed MCP server from the outside, the way hermes will.
#
# Checks the things that are easy to get wrong and hard to notice: the container
# is up but answering nothing because it bound loopback, it accepts a token it
# should reject, it advertises no tools, or its tools cannot reach the API at all.
# Each check says what a failure means rather than just what failed.
#
# Usage:
#   bash scripts/mcp-verify.sh <base-url> [mcp-token]
#
#   base-url   e.g. http://192.168.2.38:3036  (not the NachtLabs URL)
#   mcp-token  this server's own token. Read from /etc/nachtlabs-mcp/mcp-token
#              when omitted.

set -uo pipefail

BASE="${1:-}"
TOKEN_FILE="${2:-/etc/nachtlabs-mcp/mcp-token}"

if [[ -z "$BASE" ]]; then
  echo "usage: bash scripts/mcp-verify.sh <base-url> [mcp-token-file]" >&2
  exit 2
fi
BASE="${BASE%/}"

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "no token file at $TOKEN_FILE; pass it as the second argument" >&2
  exit 2
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; printf '        %s\n' "$2"; failures=$((failures + 1)); }

mcp() {
  # $1 = token ("" for none), $2 = json body
  local auth=()
  [[ -n "$1" ]] && auth=(-H "Authorization: Bearer $1")
  curl -sS --max-time 30 -X POST "$BASE/mcp" \
    -H 'Content-Type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    "${auth[@]}" -d "$2" 2>/dev/null
}

echo "MCP server: $BASE"
echo

echo "1. health check"
code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "$BASE/healthz" 2>/dev/null)"
if [[ "$code" == "200" ]]; then
  pass "healthz answers 200"
else
  fail "healthz returned ${code:-no answer}" \
    "If the container is running but this fails, it is almost certainly bound to container loopback. The image sets 0.0.0.0; check NACHTLABS_MCP_BIND and that the published port matches."
fi
echo

echo "2. the surface refuses an unauthenticated caller"
code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$BASE/mcp" 2>/dev/null)"
if [[ "$code" == "401" ]]; then
  pass "no token is refused with 401"
else
  fail "no token returned ${code:-no answer}, expected 401" \
    "A 200 or 404 here means the token check is not in front of the tool surface."
fi
echo

echo "3. a wrong token is refused"
code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$BASE/mcp" \
  -H "Authorization: Bearer definitely-not-the-token" 2>/dev/null)"
if [[ "$code" == "401" ]]; then
  pass "a wrong token is refused with 401"
elif [[ "$code" == "503" ]]; then
  fail "a wrong token returned 503, not 401" \
    "503 means the container cannot read its own token file, so it never got as far as comparing. The image runs as uid 9000: chown the files to that uid, or make them group-readable by it."
else
  fail "a wrong token returned ${code}, expected 401" "Token comparison is not rejecting correctly."
fi
echo

echo "4. the tools are advertised"
listing="$(mcp "$TOKEN" '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')"
if [[ -z "$listing" ]]; then
  fail "tools/list returned nothing" \
    "Check the container logs. A malformed or unreadable token file returns 503 with 'Server credential is not readable'."
elif [[ "$listing" != *'"result"'* ]]; then
  # Includes plain text, which is what an unreadable credential produces. Treating
  # any non-error body as success once let that pass.
  fail "tools/list did not return a JSON-RPC result: ${listing:0:160}" \
    "A 503 with 'Server credential is not readable' means the container cannot read the token file. The image runs as uid 9000, so the file must be owned by it or group-readable by it -- a root-owned 0400 file is unreadable."
else
  count="$(printf '%s' "$listing" | grep -o '"name"' | wc -l | tr -d ' ')"
  if [[ "$count" -ge 7 ]]; then
    pass "$count tools advertised"
    printf '%s' "$listing" | grep -o '"name":"[a-z_]*"' | sed 's/"name":"/          - /; s/"$//'
  else
    fail "only $count tools advertised, expected at least 7" "The registration may have partially failed."
  fi
fi
echo

echo "5. a read tool reaches the NachtLabs API"
result="$(mcp "$TOKEN" '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_projects","arguments":{}}}')"
if [[ -z "$result" ]]; then
  fail "list_projects returned nothing" "The server is not reaching the API at all."
elif [[ "$result" != *'"result"'* ]]; then
  fail "list_projects did not return a JSON-RPC result: ${result:0:160}" \
    "The token file is probably unreadable inside the container; see above."
elif [[ "$result" == *'"isError":true'* ]]; then
  fail "list_projects failed inside the tool: ${result:0:200}" \
    "The MCP server could not complete the call. A transport failure names NACHTLABS_URL in its message; the server reaching the API at all is what this check establishes."
elif [[ "$result" == *'"error"'* ]]; then
  if [[ "$result" == *"unauthenticated"* || "$result" == *"Invalid API key"* ]]; then
    fail "the API rejected the key" \
      "The key in api-key is wrong, revoked, or expired. Creating and rotating one needs a fresh Owner browser session; see docs/operations/mcp-server.md."
  elif [[ "$result" == *"scope_required"* ]]; then
    fail "the key is missing a scope" "list_projects needs projects:read."
  elif [[ "$result" == *"Forbidden"* || "$result" == *"403"* ]]; then
    fail "the API refused the connection" "Check NACHTLABS_URL, and that this host can reach that port."
  else
    fail "list_projects returned: ${result:0:200}" "See the container logs for the upstream status."
  fi
else
  pass "the API answered; the key is valid and this host can reach it"
fi
echo

if [[ "$failures" -eq 0 ]]; then
  echo "All checks passed. Give hermes: $BASE/mcp and the token from $TOKEN_FILE"
  exit 0
fi
echo "$failures check(s) failed."
exit 1
