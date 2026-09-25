# API contract — Checkpoint A

Base `/api/v1`. Authenticated Owners/Admins can read `/api/v1/openapi.json` and `/api/v1/docs`. `make api-client` exports the schema and generates TypeScript declarations during the operator handoff. Public response models deliberately exclude ORM secrets.

Errors: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Validation errors include field paths, not raw input. Responses carry a generated request ID and no-store policy. Timestamps are UTC ISO 8601; IDs are UUIDs.

Human sessions use HttpOnly opaque cookies. Mutations also require the configured Origin and `X-CSRF-Token` from the non-HttpOnly CSRF cookie. Sensitive administration requires authentication within ten minutes; `/auth/reauthenticate` refreshes that window. Service requests use a bearer key restricted to explicit project UUIDs and scopes. Current scopes: `projects:read`, `missions:read`, `validation_journeys:read`, `audit:read`. Keys cannot access human settings, approve governance, or read holdouts.

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

Work-request/webhook/run/external-effect APIs and idempotency contracts arrive in M4/M5; no nonexistent scopes are granted now.
