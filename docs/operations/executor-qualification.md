# Native executor qualification
Status: NOT RUN. This is a procedure, not an assertion that systemd settings provide proven isolation.

The small root broker performs local mirror reads, candidate hashing, trusted Git operations and systemd dispatch. It shares the host mount namespace so transient jobs see its bounded tmpfs mounts. Do not add PrivateTmp/ProtectSystem/other mount-namespace settings to the broker without redesigning that handoff. The API/worker cannot invoke arbitrary systemd commands. Untrusted agent/check processes run in separate DynamicUser units with a curated RootDirectory.

Record host/kernel/systemd version; filesystem ownership; runtime binary/library and adapter versions; catalog hash; source snapshot identifier; operator; exact commands and sanitized observations.

| Required observation | Result |
|---|---|
| RootDirectory exposes only curated tools and a single /work plus read-only inputs | NOT RUN |
| Dynamic identities cannot read API/worker keys, host homes, broker state, other jobs or system sockets | NOT RUN |
| Nested commands inherit no-new-privileges, namespace/capability restrictions and cgroup limits | NOT RUN |
| Network-disabled commands cannot connect or resolve destinations; permitted jobs reach only pinned approved addresses | NOT RUN |
| cgroup/BPF IP filtering works on this host, including IPv6; missing enforcement blocks qualification | NOT RUN |
| Cancellation/emergency stop/timeout kill grandchildren and leave no active cgroup | NOT RUN |
| Broker death/restart stops recorded unit and releases orphan tmpfs before marking jobs uncertain | NOT RUN |
| Full stdout/stderr, runaway memory/processes and excessive workspace writes terminate within limits | NOT RUN |
| Symlink, hardlink, device, submodule and traversal candidates are rejected | NOT RUN |
| Agent cannot alter authoritative candidate store, command catalog, frozen policy, Git or read-only holdouts | NOT RUN |
| Protected inputs appear only in their isolated checks and never in implementer/verifier prompts or public logs | NOT RUN |
| Hermes/OpenCode pinned versions obey intended config/tool permissions; repo plugins/instructions cannot expand privileges | NOT RUN |
| Separate verifier cannot change accepted candidate; findings match exact candidate and criteria | NOT RUN |
| Missing scanner, failed Journey, changed catalog/model/policy or stale approval prevents delivery | NOT RUN |
| Two broker processes cannot execute concurrently and lease ownership cannot be stolen | NOT RUN |

The synthetic DevelopmentAdapter emits an Invocation using /opt/checks/development_agent.py. Install that script inside the curated runtime and invoke it through the same sandbox in a development/test harness. It supports only fixture=greeting and operation=implement/verify. It is not registered as a production provider, is not used to certify external agents and has not been run.

Use a disposable project and dedicated Linux host. Never use live credentials as canaries. Do not place a real host secret in /work to test denial. A pass requires observing the denied access from inside the sandbox and checking descendants afterwards.

Qualification writes a root-only receipt tied to catalog digest and release. It is an operator attestation. Root remains trusted and can change code/configuration; filesystem controls do not defend against a malicious root administrator. The curated runtime must be maintained as part of the release.

Additional native tests are in tests/native/test_executor_boundary.py. They are skipped unless NACHTLABS_NATIVE_ACCEPTANCE=1 is explicitly set on Linux and require root plus a stopped broker. Run only on the disposable qualification host after reviewing the fixture/runtime. They cover selected boundaries, not the complete table above. All remain NOT RUN.

Agent egress is IP-based, not destination-port-based. The catalog rejects loopback, metadata and unsafe special addresses. A local Ollama used by agents must be exposed on a dedicated approved address (or a separately qualified narrow model relay); isolate it from control-plane listeners and unrelated services with host firewall/binding policy. Set allow_private_network=true only for that explicit private endpoint. The control-plane Ollama discovery/planning transport may still use its explicit loopback option. Qualify the exact listener/firewall layout; never approve a shared address that also exposes sensitive services.
