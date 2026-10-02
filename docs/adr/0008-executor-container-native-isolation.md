# ADR 0008 — Executor Container-Native Isolation (Model D)

- **Status:** ACCEPTED
- **Date:** 2026-10-02
- **Supersedes:** ADR 0006 (retired); **Affirms and extends:** ADR 0007

## Context

The executor must run untrusted generated jobs. The two stronger models were
disqualified by the release host's kernel policy:

- Unprivileged user namespaces are hard-blocked: on openclaw01
  `kernel.apparmor_restrict_unprivileged_userns = 1`, and
  `unshare -Um` under `--cap-drop ALL --security-opt no-new-privileges` fails
  with EPERM. No per-job bubblewrap/unshare sandbox is possible in-container.
- The original model additionally required root + systemd-run
  (`DynamicUser`, host cgroups), violating the ADR 0007 non-root,
  read-only-rootfs principle.

## Decision

The Docker container boundary **is** the sandbox. Jobs run as direct
subprocesses inside the executor container (uid 9000, no nested namespaces),
under per-job soft enforcement:

1. **Process isolation:** jobs run in their own process group; the broker
   kills the whole group on deadline (SIGKILL), so a wedged job cannot leak
   processes into the container.
2. **Resource limits:** per-job `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`,
   `RLIMIT_NOFILE` from job policy, plus a hard wall-clock timeout and a
   `max_output_bytes` cap.
3. **State isolation:** each job gets a private, job-scoped working directory
   under the broker's state root (`/var/lib/nachtlabs-executor/work-<id>`,
   `0700`, the ADR 0007 state-root exception), cleaned on exit.
4. **Trust:** catalog trust is signature-based, not privilege-based. The
   operator runs `qualify-executor.py` once; it emits an HMAC-SHA256
   qualification receipt over the exact catalog bytes. The broker verifies
   the signature and `catalog_sha256` on every claim. The worker signs each
   job specification with the channel key; the executor verifies the
   signature before executing (`context_for`, `job_changed` on mismatch).

## Compensating controls (ADR 0007 hardening remains fully intact)

- uid 9000, `cap_drop: ALL`, `no-new-privileges`, `read_only` rootfs
- limits: 1 GiB memory, 2 CPUs, 128 PIDs
- bridge-only network, egress to the Ollama host (192.168.2.171) only where
  the integration profile allows it (default: network disabled)
- named volumes only: `nachtlabs_config` (read-only data plane),
  `nachtlabs_executor-state` (broker state root, `0700` uid 9000)

## Evidence (observed 2026-10-02 on openclaw01)

- Executor container `healthy` under the above controls (previously
  `unhealthy` for ~28h on the pre-Model-D image).
- Job `eececb40-d90b-405e-ba26-9b6b6f205aec` (run
  `91f32876-f18a-45c2-92b4-0a0e9e98d70c`, stage `discovery`) submitted via
  the MCP bridge (SSE, `submit_work`), worker-signed specification accepted
  by the executor (HMAC path verified), lifecycle
  `queued → claimed → succeeded`, run terminated `dry_run_complete`, result
  payload sealed (master-key encrypted) and returned to the run.
- Negative test observed before the channel-key fix: the same job class
  failed closed with `job_changed` when the executor could not load the
  channel key — the fail-closed semantics of `executor_verify_spec` are
  confirmed in the live system.

## Tradeoffs accepted

1. **Shared container netns:** a malicious job that breaks userland can
   reach the container's network namespace (bridged, pinned egress). Acceptable
   because the container holds no credentials beyond the executor DB DSN and
   the network is bridge-only; internal-only exposure.
2. **Workspace on the state volume:** without a nested userns, tmpfs-per-job
   is not available to the unprivileged broker; per-job private directories
   (`0700`, cleaned on exit) on the named state volume provide the same data
   isolation boundary.
3. **Soft vs hard limits:** rlimits + process-group kill are soft against a
   determined in-container adversary, but the ADR 0007 container controls
   (no caps, no new privileges, read-only rootfs, pinned egress) bound the
   blast radius.

## Reaffirmed

ADR 0007's read-only-rootfs principle, non-root operation, and named-volume
state model remain the deployment contract. Model D changes **how** jobs are
isolated **inside** the container; it does not weaken **anything** outside
or on the container boundary.
