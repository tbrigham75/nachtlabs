# Mission and validation definitions

Each project governance document has a kind, latest version and optional approved version. Edits append immutable version rows. Approval is a separate append-only record attributed to a human. Saving a draft does not replace the active approved version. Expected-version checks reject stale edits/approvals.

A project has one Mission with purpose/users/outcomes/scope, non-goals, architectural/security/reliability constraints, escalation, unacceptable changes, risk tolerance and required Journey IDs. Approval requires at least one approved baseline Journey in the same project.

Journeys record prerequisites, setup data, steps, outcomes, evidence, method, command/adapter reference, required-on selectors, timeout, approver role, owner, enabled state and source reference. Automated methods require a command reference, but no command is executed at this checkpoint. Last-run data stays null.

Holdout bodies use a separate encrypted table; generic version content is empty. Only human Owners/Admins can retrieve definitions. Access/edit/history actions are audited without content. Independent verification and protected execution are M7 work; encrypted definitions alone do not establish runtime isolation.
