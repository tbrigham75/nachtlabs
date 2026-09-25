# Milestone 4 operator handoff

**Source authoring only. No checks have run.** Current handoff: m4-source-2026-09-25. Implementation stops before M5.

## First Linux startup

Use the [foundation setup guide](checkpoint-a-testing.md) in its documented order. The current migration head is **0002**, including 0001. Apply both on fresh installations, or upgrade 0001 to 0002; reapply scripts/grants.sql to the chosen database. No migration occurs at service startup.

Generate real locks and OpenAPI/types, format, build and run the deferred checks on Linux when you choose. Preserve tool versions and sanitized failures in [results](../planning/milestone-4-results.md). No Windows check has substituted for those steps.

Default API/worker configuration includes:

```text
NACHTLABS_INTEGRATION_NETWORK_ENABLED=false
NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED=false
```

Keep both false for configuration-only testing. No provider traffic is sent by saving a connection, model, agent or credential.

## Configuration-only acceptance

1. Sign in as Owner/Admin. Open Integrations; add a GitHub, Gitea or Ollama connection with an explicit approved IP. Credentials do not belong in the URL.
2. Verify provider checks show disabled. A direct POST to queue a probe must also reject the request.
3. Enter synthetic credentials. Reload/list/detail/audit must never return them. Replace, revoke, and try an old version number; stale writes must conflict.
4. Change a destination IP/port or transport setting. Credentials should clear and old discovery should become inapplicable.
5. Add implementation and verifier model profiles, then Hermes/OpenCode configurations. Expected versions remain untested; execution stays unavailable.
6. Try the same reads/mutations as a Viewer and a scoped service-account key. Both must be denied administrative integration access.
7. Test archived-project governance approval, password-input clearing and earlier Checkpoint A identity/governance flows.

## Optional future permitted Ollama discovery

This is an operator procedure for a later authorized environment, not a request to run it now. Permit a controlled Ollama endpoint, then set only NACHTLABS_INTEGRATION_NETWORK_ENABLED=true in both protected api.env and worker.env and restart those services. Keep the Git switch false.

Use HTTPS for non-loopback servers; set NACHTLABS_INTEGRATION_CA_FILE in worker.env to a protected, administrator-installed CA bundle when needed. Never disable TLS verification. Loopback HTTP needs explicit private and HTTP permission in that connection.

Queue a check. Expect pending → running → succeeded/failed, a measured duration and actual reported models/version on success. Failure must contain a fixed error code, not raw provider messages. Try denied private/metadata addresses, redirects, bad certificates, invalid credentials and a stale configuration change during a check. Discovery is not model-generation or agent-compatibility evidence.

## Git restriction remains

Do not enable NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED or perform live remote discovery under the current organization restriction. Source and synthetic contract tests are available; actual GitHub/Gitea repository selection acceptance remains deferred until explicitly authorized in an organization-permitted environment. No plugin/CLI/API workaround is authorized.

## Encryption maintenance

Read [rotation](key-rotation.md) and [backup/restore](backup-and-restore.md). Use a disposable installation first. Record MFA, holdout, mail and integration credential decryption before/after rotation, plus alternate-database restore. Do not overwrite active keys.

## Deferred execution and acceptance

Agent executable/version checks, invocation, tool isolation, timeout and process-group cancellation need a restricted development runner in M6. No check button fabricates that evidence. Model-generation code is internal only. Webhook primitives have no public intake route.

Run the authored unit/frontend/PostgreSQL tests only when you choose to start Linux testing. Integration fixtures require schema 0002 in a dedicated database ending _test. All build/type/lint/format/security/restore outcomes are currently NOT RUN.
