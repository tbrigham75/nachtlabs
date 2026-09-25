# Source review before and during M4

This is a source review, not a passed test report. Reviewed the existing API/auth/access paths, persistence/migrations, worker, encryption/recovery, native scripts/units, frontend forms/routes/transport, and authored test definitions. Added M4 source received the same review.

## Corrections authored

| Finding | Correction | Pending evidence |
| --- | --- | --- |
| Archived project could still approve governance | Archive guard with project-row locking before edits/approvals | Concurrent archive/approve integration test |
| SQLAlchemy identity map could retain pre-lock state | Refresh objects when obtaining mutation locks | Concurrent version/security mutation tests |
| Disabled approved Journey could satisfy Mission baseline | Require enabled content in the approved Journey version | Disabled-baseline rejection |
| Independent rate-limit transaction could compete with saturated request pool | Separate small database pool for rate-limit writes | Saturation/concurrency acceptance |
| Invalid bearer guesses lacked the valid-key limit | Apply source limit before bearer lookup | Rate-limit acceptance |
| Worker crash at final email attempt left sending state | Expired exhausted lease becomes failed | Worker interruption test |
| Server framework traceback could include exception material | Safe server diagnostic formatter; no raw traceback/text | Deliberate canary failures and journal inspection |
| Successful password forms retained values | Clear password inputs after successful submission | Frontend test/manual check |
| Non-JSON proxy errors became raw parsing errors | Controlled client error message | Proxy failure browser check |
| Recovery backup published directly to final filename | Publish completed encrypted file atomically from partial | Interrupted encryption test |
| Snapshot/restore did not cover retired encryption keys | Versioned four-member snapshot, alternate key outputs and schema guard | Key-rotation/restore drill |
| Provider endpoint edits could redirect stored credentials | Destination/transport changes clear credential material | Credential lifecycle integration definitions |
| Queued provider result could outlive its configuration | Bind probes/results to version; discard changed/revoked results | Worker race definitions |

## Limits

Source review cannot establish that dependencies resolve, schemas migrate, TypeScript compiles, services start, layouts render, or defenses hold under actual concurrency. No builds, tests, type/lint/format checks, migrations, scans, services, health checks or provider probes were executed.

No blanket claim that all bugs are removed is made. Preserve the pending Linux acceptance work, including the earlier identity/governance tests and the new integration/rotation cases.
