# API contract — Checkpoint A

Base `/api/v1`. Authenticated Owners/Admins can read `/api/v1/openapi.json` and `/api/v1/docs`. `make api-client` exports the schema and generates TypeScript declarations during the operator handoff. Public response models deliberately exclude ORM secrets.

Errors: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Validation errors include field paths, not raw input. Responses carry a generated request ID and no-store policy. Timestamps are UTC ISO 8601; IDs are UUIDs.

Human sessions use HttpOnly opaque cookies. Mutations also require the configured Origin and `X-CSRF-Token` from the non-HttpOnly CSRF cookie. Sensitive administration requires authentication within ten minutes; `/auth/reauthenticate` refreshes that window. Service requests use a bearer key restricted to explicit project UUIDs and scopes. The full scope set is `projects:read`, `missions:read`, `validation_journeys:read`, `audit:read`, `work_requests:create`, `work_requests:read`, `runs:read` (`apps/api/src/nachtlabs_api/access.py` is authoritative; this file previously listed four of the seven). Keys cannot access human settings, approve governance, or read holdouts.

## Driving it from an agent

Prefer the MCP server in `packages/mcp-server` over calling these routes directly. It is a thin, stateless bridge that gets three things right that are easy to get wrong by hand:

- `Idempotency-Key` on submit is a hash of the request body. The header is required and deduplicated on, so a retry after a timeout must reproduce the same key or it creates a second run for the same request.
- A run in `awaiting_approval` is reported as a wait, not an error. Every plan requires a human: approvals are stored against a user row, the project carries a database constraint that cannot be disabled, and the executor re-checks the approver is still an active owner, admin or operator. No key can clear this state, so a client that treats it as failure retries forever.
- `DomainError` codes such as `mission_required`, `baseline_required` and `stale_governance` are translated into sentences that say what a person has to do. A bare "HTTP 409" tells a model nothing.

A minimal direct call, if you are writing a client rather than running the MCP server:

```bash
curl -X POST http://<nachtlabs-host>:3035/api/v1/work-requests \
  -H "Authorization: Bearer nl_..." \
  -H "Idempotency-Key: $(printf '%s' "$BODY" | sha256sum | cut -c1-40)" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"<uuid>","title":"...","description":"...","acceptance_criteria":["..."]}'
```

`POST /work-requests` is the only route a key may create work through. There is no outbound notification and no push channel: `/runs/{id}/stream` requires a browser session and answers `403 human_required` to a key, so a client polls `GET /runs/{id}/events?after=N`.

Rate limiting is keyed on the API key (300 per five minutes), not on the caller's address. An earlier version also counted authenticated traffic against a per-source bucket, which was one shared bucket for the whole installation because no proxy preserves the client address through the interface. See `docs/planning/linux-verification-2026-09-28.md`.

### Creating credentials

Key creation requires a human browser session authenticated within the last ten minutes, and the raw value is returned exactly once:

1. `POST /service-accounts` `{"name":"hermes"}`
2. `POST /api-keys` with that `service_account_id`, the scopes above, the project UUIDs, and an `expires_at`. Set one: a key cannot rotate or revoke itself, so expiry is the only unattended safety net.

Give a machine the smallest set that does the job, and bind it to one project. Both are enforced server-side; `NACHTLABS_PROJECT_IDS` on the MCP server repeats the project bound list locally so a mistake names the configuration instead of arriving as a confusing 404.

| Resource | Purpose |
| --- | --- |
| `/auth/setup-status`, `/auth/setup` | One-time initialization |
| `/auth/login`, `/auth/logout`, `/auth/me` | Session lifecycle |
| `/auth/mfa/enroll`, `/auth/mfa/confirm`, `/auth/mfa/verify`, `/auth/mfa/disable` | MFA lifecycle/challenge |
| `/auth/forgot-password`, `/auth/reset-password`, `/auth/accept-invitation` | Expiring single-use links |
| `/auth/preferences`, `/auth/reauthenticate` | Theme and sensitive-action window |
| `/organization`, `/users`, `/invitations` | Administrative access |
| `/projects`, `/projects/{id}`, `/projects/{id}/members` | Draft projects, archive, membership |
| `/projects/{id}/governance/{kind}` | Mission/Journey/holdout versions |
| `.../{documentId}/history`, `.../{documentId}/approve` | History and approval |
| `/service-accounts`, `/api-keys`, `.../{id}/revoke`, `.../{id}/rotate` | Scoped credentials |
| `/audit-log`, `/audit-log/export` | Authorized records/export |
| `/health/live`, `/health/ready`, `/overview` | Process/schema readiness and worker heartbeat |

Audit filters: exact `action`, optional `project_id`, `limit` 1–100, opaque `cursor`; responses contain `items` and `next_cursor`. Export is JSON up to 1,000 authorized records; larger exports use pagination. Project/admin lists target the bounded initial installation.

Key creation returns the raw value once. Listing omits raw values/verifiers. Rotation overlaps for at most 24 hours; revocation takes effect on the next request. Never use tokens in URLs or logs.

Work-request, webhook, run and external-effect APIs exist; the idempotency contract is described above. No nonexistent scopes are granted.
