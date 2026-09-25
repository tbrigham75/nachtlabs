# Secrets and redaction

Passwords: Argon2id. Random session/API/link tokens: SHA-256 verifiers. Recoverable MFA enrollment/seeds, holdout bodies and transient mail: AES-256-GCM with random nonces, key IDs and record-bound associated data. The 32-byte base64 master key lives in a protected Linux file. The web service does not receive it.

API keys, TOTP setup material and recovery codes are disclosed only during authorized creation. Client state is in memory; no credentials use localStorage/sessionStorage. Identity links use fragments, removed after capture, so tokens do not enter server URL logs.

Application JSON logs select route templates, request IDs, timings, outcomes and error class names. They omit bodies, headers, raw URLs, bound SQL values and raw exception text. Audit uses explicit safe fields plus recursive sensitive-key redaction. This is not a promise that arbitrary raw text can always be sanitized: raw tool/model/source streams are not ingested at this checkpoint.

Successful mail payloads are erased, retries bounded and encrypted payloads expire after three days. Session/challenge/rate cleanup is separate from audit retention. No audit deletion interface is exposed.

M4 supplies an offline rotation script and retained-key decryption. Follow [key rotation](../operations/key-rotation.md); its runtime/restore acceptance is NOT RUN. Never overwrite the active key. Unknown key IDs still fail closed.
