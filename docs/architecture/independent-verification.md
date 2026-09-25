# Evidence and independent verification
Candidate identity is SHA-256 over a sorted manifest of relative paths, file digests, byte counts and executable bits. A new identity cannot reuse prior candidate evidence. Symlinks, linked files, device files, submodules, reserved directories and scope escapes are refused.

Each command/check runs on a fresh working copy. Registered script/API/browser/integration/external commands are installed or approved by the Linux administrator; browser text cannot supply arbitrary commands. Manual Journeys require a versioned human attestation at the configured role. Command exit status, byte counts and catalog fingerprints are recorded; raw output is not published.

Protected content is decrypted only for the matching isolated holdout command. Implementers and verifiers see only generic protected-result status, not definitions or raw output. Evidence payloads are encrypted and immutable; protected reads require administrative authorization and audit.

Verifier configuration must differ from implementation; distinct model identity is required by default. It receives a fresh copy, approved plan, criteria, Mission and safe evidence metadata. It must leave candidate files unchanged and write a bounded structured finding. A pass requires an exact candidate and every criterion true. Pass-with-warnings, rework, failed and human-review-required outcomes stop delivery.

A policy may explicitly allow an Owner to accept pass-with-warnings for one candidate/finding, with a reason and one-hour expiry. All hard gates and criteria still apply. There is no exception for missing/failed validation, secrets, scope or uncertain execution.
