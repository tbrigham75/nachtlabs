# ADR 0005: bounded discovery and offline key rotation

Accepted for M4 source authoring; runtime unverified.

Use one versioned connection record with provider-specific adapters and a PostgreSQL discovery queue. Keep network switches outside browser-controlled configuration, with Git disabled independently. Pin a numeric destination and retain hostname TLS verification; no automatic redirects, DNS fallback, proxy inheritance or public HTTP.

Separate configuration, discovery success, compatibility proof and execution readiness. Persist expected agent versions without pretending they were checked. M6 supplies the restricted runner; M4 adds no execution endpoint. Initial GitHub auth is narrow PAT mode; App exchange remains future work.

Use write-only AES-GCM credential replacement and revocation. Changing destinations invalidates credentials and probe evidence. Keep master-key rotation as offline root maintenance, writing recovery keys before a transaction rewrites every encrypted column. Backups include active and retained keys. Online rotation would add distributed coordination without demonstrated need at this milestone.
