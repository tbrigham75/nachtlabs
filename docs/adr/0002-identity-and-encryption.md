# ADR 0002: sessions and recoverable secrets

Use random server sessions with verifier storage, Origin/CSRF, Argon2id, durable rate limits, optional privileged TOTP policy, operator-held setup token and organization-row ownership locking. Fixed roles plus membership are the initial access model.

Random API/link tokens are hashed. Recoverable values use vetted AES-GCM with record-bound associated data and a protected master-key file. Web has no backend credentials; no browser credential storage. Multi-key rotation waits for M4 with restart/restore design requirements.
