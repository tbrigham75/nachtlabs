# NachtLabs — Operator Runbook (Zero → Live Run)

Canonical path from a fresh install to a completed LLM-driven run.
Every step is verified against the code (core 0.1.0, Model D executor).
Split by surface: **Browser** (`http://openclaw01:3035`) or **Host console**.

Order matters. The API enforces: connection → discovery (probe) →
model profiles → agent → project integration → execution gate → run.

---

## Phase 0 — Preflight (Host console)

```bash
cd ~/projects/web-app/nachtlabs
docker ps | grep nachtlabs        # api, worker, executor, postgres, web, mcp
docker exec nachtlabs-postgres-1 psql -U nachtlabs_api -d nachtlabs -c '\dt'
curl -s http://192.168.2.171:11434/v1/models   # Ollama (Beast) reachable
```

Required tables present after `scripts/seed.sh`:
`organizations, users, service_accounts, api_keys, projects,
project_members, governance_documents, governance_versions,
holdout_contents, governance_approvals` + the empty integration stack:
`integration_connections, integration_probes, model_profiles,
agent_configurations, project_integrations, project_policies`.

---

## Phase 1 — Connection (Browser wizard)

Settings → LLM setup → **Connection** step.

- Provider: `ollama`
- Base URL: `http://192.168.2.171:11434/v1`
- Pin: `192.168.2.171`
- **Blocker:** private IP + cleartext HTTP is refused unless the
  deployment switch is on. Host console:

```bash
# both API and worker need these (compose env or /etc/nachtlabs config), then:
docker compose restart api worker
NACHTLABS_INTEGRATION_NETWORK_ENABLED=true
NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true
```

Without both flags set **before** save, pinning a private HTTP address is
rejected. No wizard button fixes this — it is an installation-level change.

## Phase 2 — Discovery (Browser wizard)

The worker probes `/v1/models` and records a probe row
(`integration_probes.state = succeeded`). Save the probe id — Phase 4
references it. A saved connection is **not** a working one; a successful
discovery is the first evidence.

## Phase 3 — Profiles + Agent (Browser wizard)

Profiles (role is the constraint):

| profile | role | model | purpose |
|---|---|---|---|
| `qwen-impl` | implementation | `qwen3.8:27b` | executor-side write |
| `gemma-verify` | verifier | `gemma4:26b` | executor-side read-only |
| `qwen-plan` | planning | `qwen3.8:27b` | worker-side plan author |

Rules the API enforces:
- `require_distinct_models` defaults **true** → impl and verifier must be
  different models. There is no override.
- Planning runs in the **worker** (Ollama adapter); impl + verifier run
  in the **executor** (opencode adapter).
- Agent row: `provider = opencode`, `executable = /opt/nachtlabs-runtime/bin/opencode`,
  `expected_version = 1.17.13`, one agent bound to the verifier profile and
  one to the implementation profile; a third profile binding for planning.

## Phase 4 — Project integration (Browser)

Project settings → integration: repository key + default branch, bind the
discovery probe id, select implementation agent + verifier agent.
This writes `project_integrations` + `project_policies` (policy JSONB,
`extra="forbid"`, keys):

```json
{
  "planning_profile_id": "<uuid-qwen-plan>",
  "allowed_paths": ["docs/"],
  "max_changed_files": 5,
  "validation_commands": [["python3", "checks/demo_doc.py"]],
  "journey_commands": []
}
```

`allowed_paths` is the scope gate whitelist (`execution/files.py:71`):
**every** changed file must be under one of these prefixes and must not be
in `PROTECTED` (`.opencode/`, `.hermes/`, `.github/`, `.gitea/`, `.agents/`,
`node_modules` is not protected but still counts as changed).

## Phase 5 — Execution gate (Host console, root)

The API cannot do this two things. Both are host-level:

1. **Runtime pins.** The executor verifies a SHA-256 pinned catalog
   (`/etc/nachtlabs/execution-catalog.json`, ≤1 MiB, no symlinks,
   not group/world writable). Every executable the catalog names must be:
   - a real file at `<runtime_root>/<name>` (resolve == target, no symlink),
   - in `runtime_files` pins with correct digest,
   - the digest must match byte-for-byte.
2. **Qualification receipt.** `/etc/nachtlabs/executor-qualification.json`
   must carry `qualified: true`, `release: "0.1.0"`,
   `catalog_sha256: <sha256 of raw catalog bytes>`, and
   `qualification_hmac: <hmac-sha256 over raw catalog bytes with the
   32-byte key in /etc/nachtlabs/credentials/executor-qualification-key
   (base64, 44 chars, decoded = 32 bytes, 0640 root:9000)>`.

Re-mint the receipt after **every** catalog edit:

```bash
python3 - <<'PY'
import base64, hashlib, hmac, json
cat = b"/etc/nachtlabs/execution-catalog.json"  # or the real path
raw = open(cat, "rb").read()
key = base64.b64decode(open("/etc/nachtlabs/credentials/executor-qualification-key","rb").read().strip())
receipt = {
  "qualified": True,
  "release": "0.1.0",
  "catalog_sha256": hashlib.sha256(raw).hexdigest(),
  "qualification_hmac": hmac.new(key, raw, hashlib.sha256).hexdigest(),
}
open("/etc/nachtlabs/executor-qualification.json","w").write(json.dumps(receipt, indent=2))
PY
docker restart nachtlabs-executor
```

3. **Egress policy** in the catalog: `allowed_addresses: ["192.168.2.171"]`
   and `allow_private_network: true` (catalog.py:196-208 rejects loopback,
   link-local, reserved, and private without the flag).

## Phase 6 — First run (Browser)

Project → New work request → short, single-intent prompt
(e.g. *"Create `docs/greeting.md` with one line: Hello from NachtLabs."*).
Submit as **non-dry-run**.

Pipeline stages (`workflows/engine.py` + `execution/stages.py`):
1. **Plan** — worker, planning profile. Produces plan JSON.
2. **Approve** — `plan_approval_required=true` → you approve in the UI.
3. **Discovery** — executor clones candidate.
4. **Implementation** — executor, opencode (impl model). Writes files.
5. **Validation** — scope gate + validation commands + secret scan.
6. **Verification** — executor, opencode (verifier model, distinct).
   Writes `./nachtlabs-verdict.json` (CWD-relative).
7. **Delivery** — gated (Gitea HTTP-only in this install). Run halts at
   `verification` with the verdict available.

---

## Gate-error quick reference

| error | meaning | fix |
|---|---|---|
| `executor_unqualified` | HMAC/sha/receipt mismatch | re-mint receipt (Phase 5.2) |
| `runtime_changed` | pinned file bytes ≠ catalog digest | re-pin or re-re-mint |
| `runtime_unpinned` | executable missing from `runtime_files` | add pin |
| `catalog_symlink` / `runtime_pin` | symlink or `..` in pin path | use real files |
| `scope_violation` | changed file outside `allowed_paths` | widen `allowed_paths` or clean cruft |
| `protected_path` | write into `.opencode/`, `.hermes/`, … | can't allow; clean before diff |
| `unsafe_workspace` | symlink dir / `.git` / `.nachtlabs` in candidate | remove from workspace |
| `workspace_budget` | candidate > byte/file limit | raise `max_workspace_bytes` |
| `change_budget` | > `max_changed_files` changed | raise limit or scope work |
| `verification_divergent` | verdict model ≠ impl model or verdict invalid | check profile bindings |
| `external_directory` | impl wrote outside workspace | check prompt, opencode config |
| `network_policy` | egress without pinned addresses | set `allowed_addresses` |
| `plan_mismatch` | approved plan hash ≠ current plan | re-approve after plan change |

---

## Invariants (do not violate)

- `HMAC = hmac(b64decode(key), raw_catalog_bytes)` — over raw bytes, not digest.
- Key file: 32 raw bytes = 44 base64 chars, `0640 root:9000`. Executor (uid 9000) needs read.
- Executor `PATH` for jobs: `<runtime_root>/bin:/usr/local/bin:/usr/bin:/bin`.
- Sandbox env is **fixed**: `PATH, LANG, HOME=workspace, TMPDIR=workspace/tmp, NACHTLABS_EXECUTOR_JOB=1`. No inherited env.
- opencode must find model config at `<workspace>/opencode.json` (HOME=workspace — that's where it looks).
- `require_distinct_models` is always true. No exception.
- Delivery: pr_only, gated off (HTTP-only Gitea).
- The executor container IS the sandbox (Model D). No nested Docker, no namespaces.
