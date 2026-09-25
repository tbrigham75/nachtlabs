# Work, execution and monitoring API
Prefix /api/v1. Browser mutations require same-origin CSRF; human approval/admin configuration also requires recent authentication. Service keys may have work_requests:create, work_requests:read and runs:read within their assigned projects. They cannot approve plans, attest, cancel, configure policies or accept exceptions.

- POST /work-requests and /regressions: bounded WorkInput; Idempotency-Key required. Reuse with changed content conflicts.
- GET /work-requests?project_id=UUID and /work-requests/UUID: intake and linked runs.
- GET /runs?project_id=UUID and /runs/UUID: public projections, plan, candidate and safe evidence metadata.
- POST /runs/UUID/approval: expected_version, digest, decision, reason.
- POST /runs/UUID/cancel or /replan: expected_version, reason.
- POST /runs/UUID/attestations: expected_version, candidate, journey_id, outcome, evidence.
- POST /runs/UUID/accept-verifier-warnings: Owner only; expected_version and reason; policy opt-in.
- GET /runs/UUID/events?after=N and /stream with Last-Event-ID: replay and authorized SSE.
- GET /runs/UUID/evidence/EVIDENCE_UUID: protected items are administrative and audited.
- GET/PUT /projects/UUID/execution-policy: expected_version plus validated configuration.
- GET/POST /workflows: immutable definition versions.
- GET/PUT /projects/UUID/webhook: signed intake binding; delivery endpoint /hooks/BINDING_UUID has HMAC authentication.
- GET/PUT /factory-control: administrative emergency stop.
- GET /monitoring, /logs, /incidents, /incidents/UUID; incident /actions records expected version, action and note.
- GET /recommendations; POST /recommendations/UUID/actions uses version, digest, action and reason.
- GET /notifications; POST /notifications/UUID/read.
- GET/POST /saved-searches; GET/PUT /retention.

OpenAPI export/generation remains operator-run and NOT RUN. Error responses use fixed codes and never reflect raw provider/process exceptions.
