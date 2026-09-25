# Durable workflow engine
Migration 0003 introduces versioned workflow definitions, requests, runs, immutable events/approvals/evidence and executor jobs. Intake serializes on the project row before checking actor/project/idempotency identity. Identical replay returns the original request; a changed body or regression kind conflicts.

Snapshots include the approved Mission, enabled baseline Journey versions, optional holdout version IDs, project policy and agent routing. Protected content is fetched only by its isolated validation stage. Planning receives repository inventory and normal governance context. Non-aligned Mission assessments stop for review.

Stages are planning/discovery, approval, implementation, validation, optional human attestation, independent verification and delivery. The ordinary worker persists dispatch; a separate qualified broker executes jobs. Durable waits survive restart. Current human authorization, governance, policy, model/catalog identity and approval digest are checked before execution. One claimed/running job is enforced by PostgreSQL and one broker per host by flock.

Replanning consumes a finite budget and always produces a fresh approval digest. Unknown process/delivery outcomes require reconciliation. There is no automatic mutation retry. Events have per-run sequence numbers; SSE reauthenticates every batch and supports Last-Event-ID. Event payloads contain explicit safe metadata.

Native execution and provider behavior remain NOT RUN. See the qualification and recovery documents.
