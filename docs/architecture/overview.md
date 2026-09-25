# NachtLabs architecture

Separate native API, web and worker processes share a PostgreSQL source of truth. The API owns authorization and mutations. Next.js calls same-origin versioned HTTP endpoints; it never accesses PostgreSQL or external AI/Git providers. The ordinary worker handles mail, identity cleanup, provider probes, durable workflow dispatch and monitoring. A separate qualified native broker handles isolated agent/check jobs and trusted target Git delivery.

`packages/core` contains identity/security services, access policies, persistence and audit insertion. API modules group routes by authentication, administration, governance and observation, with explicit request/public response projections. Transactions are short; SMTP runs outside the API transaction. Rate limits commit independently so failed requests cannot roll them back.

The initial migration is a frozen SQL snapshot independent of current model metadata. The schema owner runs migrations; API and worker receive separate grants. Audit/version/approval rows reject updates/deletes. A DB trigger checks matching organization IDs for project membership.

Owner setup uses an advisory transaction lock and singleton organization constraint. Ownership/security edits serialize on the organization row. Project membership and key scopes are enforced before data access.

Identity links store token hashes. Their transient mail payloads are encrypted and bound to a job ID. The worker claims mail with SKIP LOCKED and a lease, commits, sends SMTP, then records the result for that lease. Retries are bounded. Delivery is at least once; consuming a link remains single-use.

Workflow/executor/provider source is present through M10. Native execution remains gated on operator qualification, and both network switches default off. All runtime behavior awaits operator verification.

M4 adds integration configuration/discovery. M5–M10 add workflows, isolated execution, evidence, Git delivery and operations. See workflow-engine.md, independent-verification.md, git-workflow.md and regression-workflows.md.
