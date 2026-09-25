# Protected holdouts

Only human Owner/Admin identities may read/write protected definitions or history. Service keys and other roles are excluded. Generic project/Journey responses contain no protected body. The `holdout_contents` table stores authenticated ciphertext bound to the version UUID; generic version content is empty and its name is non-descriptive.

Access/edits are audited by ID/version, never instructions or expected results. The UI requests holdouts only on the authorized screen. Responses are no-store and logout clears the client query cache. No persistent browser storage is used.

There is no holdout execution in Checkpoint A. M7 must isolate protected tests/artifacts from implementers, use a separate verifier identity, filter feedback, bound retries and exercise leakage tests across prompts/logs/files/exports. At-rest encryption alone is not that execution boundary.
