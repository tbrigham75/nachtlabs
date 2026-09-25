# Native service hardening

API, worker and web have separate non-root users and root-owned installed code. Templates restrict writable paths, capabilities, namespaces, address families, kernel/control-group access, CPU/memory/tasks, restart behavior and process-group termination. They use NoNewPrivileges, ProtectSystem=strict, ProtectHome and PrivateTmp.

Node V8 needs JIT executable memory, so its unit omits MemoryDenyWriteExecute. API/worker request it; operator verification must establish native-library compatibility. Document a narrow justified exception instead of disabling an entire hardening profile.

The ordinary worker dispatches durable jobs but never runs agent/repository processes. A separate root broker and isolated transient job units are authored for M6–M10. The broker shares the host mount namespace to hand bounded tmpfs mounts to systemd; it is a privileged trust boundary, not an untrusted-code sandbox. Qualification remains required. Address-family limits alone do not constitute a destination allowlist; actual cgroup egress enforcement must be tested. See ../operations/executor-qualification.md.

Operator checks: systemd-analyze verify; effective User/Group and unit paths; systemd-analyze security as advisory input; permitted/denied file access under each identity; restart/reboot; recent authenticated worker heartbeat. A hardening score is not proof. All these checks are not run at handoff.
