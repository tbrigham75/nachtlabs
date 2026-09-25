# Integration architecture

Owner/Admin sessions configure connections, replace encrypted credentials and explicitly queue discovery. Service-account keys cannot manage or read these configurations. Sensitive mutations require recent authentication, same-origin requests and CSRF protection.

PostgreSQL stores connection versions and queued probes. The worker claims one probe, records credential use, performs bounded read-only discovery outside the transaction, then commits only if the lease and connection version still match. Worker interruption marks a lease failed; it does not replay provider requests silently. A destination/credential change invalidates earlier evidence. An in-flight request may complete after revocation, but its result is discarded.

Both installation switches default false. INTEGRATION_NETWORK_ENABLED controls provider calls; GIT_PROVIDER_NETWORK_ENABLED independently gates GitHub/Gitea calls. UI changes cannot enable either switch.

Every destination uses an explicit numeric IP pin. HTTP connects to that IP without DNS or environment proxy lookup; HTTPS verifies the configured hostname and optional administrator-installed CA. Redirects are errors. Metadata/link-local/multicast/unspecified/reserved addresses are rejected; private/loopback access requires explicit permission. HTTP is loopback-only. Responses are size-bounded and parsed into allowlisted repository/model fields. Raw provider errors, headers, credentials and agent text are not telemetry.

Credentials use AES-GCM with record-specific associated data. They are absent from read responses and probe snapshots. Replacement replaces all credential fields; changing destination clears them. No plaintext token is returned after entry. Offline master-key rotation rewrites all ciphertext in one transaction while services are stopped.

Agent adapters construct invocation specifications for a future restricted runner. Hermes and OpenCode have distinct input/event contracts. Cancellation belongs to the runner's entire process group. Exit zero is an agent completion claim, not validation. There is no native subprocess runner, public agent execution or workflow dispatch in M4.

Model profiles separate implementation/verifier/planning roles. Project selection requires repository metadata from a successful current-version discovery within 24 hours. Agent/profile references are checked for organization, role and active status. Distinct model identifiers are a configuration rule, not proof of independent validation. Runtime must re-evaluate all routing before every execution.

Webhook primitives verify HMAC against raw bytes, bound body size and produce delivery/body fingerprints. M5 intake must persist uniqueness, reject ID/body conflicts and authorize repository/actor/trigger. Neither provider signature alone nor these primitives authorize execution.
