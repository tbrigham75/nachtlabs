# Source review: M5–M10 continuation
Source reading and editing only; no lint, parser, type checker, build or test execution.

Corrected during authoring:
- Serialized idempotency checks under project locks and included run kind in the request fingerprint.
- Added worker fairness while waiting for executor jobs and rollback before persisting internal errors.
- Bound approval to frozen governance/policy and runtime catalog/agent versions.
- Kept privileged broker mounts visible to transient units; isolated children retain their own restrictions.
- Confirmed cgroup inactivity before releasing workspace state; restart cleanup retains uncertain outcomes.
- Separated command working copies from authoritative candidates and omitted raw output from public evidence.
- Added explicit offline agent routing without requiring a live Git provider.
- Extended runtime grants, schema readiness, key rotation and backup instructions for new persistence.
- Replaced obsolete M4 UI placeholders with run/monitoring controls and current qualification wording.
- Preserved network-off defaults, disabled schedules and no remote Git execution.

This review does not establish correctness. The first Linux pass must include source quality, database-role integration, migration/restore and actual sandbox/provider failure paths. Particularly scrutinize privileged broker code, systemd property support, tool auto-configuration, Git/libcurl pinning, filesystem mount cleanup, lease recovery and key rewrapping.

Additional review correction: Ollama message content now permits normal multiline text/JSON while provider identifiers retain strict control-character rejection. A regression test was authored; it was not run.
