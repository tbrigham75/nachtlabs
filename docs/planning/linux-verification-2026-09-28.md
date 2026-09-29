# Linux verification pass — 2026-09-28

This record reports what was actually executed, separately from what the source claims.
It corrects a standing problem: source through Milestone 10 was authored on Windows
PowerShell with no checks run, and the repository's live documents continued to assert
that state after execution had begun.

## Environment actually used

| Component | Value |
|---|---|
| Kernel | `Linux 6.18.33.2-microsoft-standard-WSL2` |
| Init | systemd 259 (WSL2 with systemd enabled) |
| Python | 3.12.14 (uv 0.12.19) |
| Node | v24.21.0 (LTS "Krypton"), installed to `~/.local/node-v24.21.0-linux-x64` |
| pnpm | 10.0.0, via corepack |
| Next.js | 16.x |

**This is WSL2, not a native Linux host.** Earlier documents state that WSL is blocked
for authoring. That constraint is now contradicted by the working environment, and it is
recorded here rather than quietly removed. What this means for evidence:

- Interpreter, type, lint, format, unit and build results are trustworthy as source
  correctness signals. They are exactly the class of check that does not depend on the
  init system or on service isolation.
- **No result below is evidence about native Linux deployment.** systemd unit behavior,
  DynamicUser isolation, cgroup limits, the privileged broker boundary, executor
  qualification, backup/restore and key rotation all require a real Ubuntu 24.04 host.
  Those rows in the acceptance matrix stay NOT RUN.

The Node 24 tarball was verified against the official `SHASUMS256.txt` before install.
The previous Node 22 install is retained at `~/.local/node-v22.23.2-linux-x64`.

## Defects found and fixed

1. **`scripts/update.sh` could not activate a bundle on a tree that never built.**
   `apps/web/public/docs-assets/` is gitignored (`.gitignore:26`), so the directory has
   no tracked existence. Activation used `cp -a` into a parent that was absent, failing
   with `cp: cannot create directory ... No such file or directory`. In practice this was
   masked because a prior `build.sh` had left the directory behind. Fixed by `install -d`
   on the parent before the copy, matching the existing `build.sh:3` idiom. Covered by a
   new test, `test_update_activates_when_the_gitignored_public_directory_is_absent`.

2. **`scripts/recover-owner.py` reported the wrong error to a non-root operator.**
   Commit `4f29965` added `require_operator_env()` above the root check, so a caller
   without root was told to run `configure.py` instead of being told root is required.
   A non-root process cannot read `/etc/nachtlabs`, so that message was never actionable.
   The root check now runs first. This surfaced only because the integration tests were
   run outside `make test`'s default selection.

3. **The last commit was never run through the formatter.** Three files failed
   `make format-check`: `tests/native/test_maintenance_scripts.py` (ruff),
   `apps/web/src/features/llm-setup.tsx` and `apps/web/tests/llm-setup.test.tsx`
   (Prettier). Reformatting was whitespace-only; the diff was reviewed line by line.

4. **The documented toolchain was absent.** `package.json` requires Node `>=24 <25` and
   pnpm `>=10 <11`; the host had Node 22.23.2 and pnpm 9.15.0. Every `pnpm`-shelling
   `make` target failed outright — `lint`, `typecheck`, `build`, `test`, `format-check`,
   `api-client`, `test-e2e` — which is the entire operator workflow in the README. This
   was an environment gap, not a source defect; the code passed once the pinned versions
   were installed.

5. **`make build` left the working tree dirty, which would have blocked every later
   update.** `apps/web/next-env.d.ts` was still the pre-Next-16 two-line form, so a build
   rewrote it. `scripts/update.sh:23` refuses to run against a dirty tree, so an
   installation that had ever been built could never be updated again — the operator
   would be told "the working tree is dirty" with no way to satisfy it. The regenerated
   file is deterministic (two consecutive builds produce identical bytes) and typecheck
   still passes with `.next` absent, so the correct fix is to commit the regenerated file
   rather than ignore it. **This one still needs to be committed**; until it is, a
   post-build tree is dirty.

## Results

| Check | Command | Result |
|---|---|---|
| Python tests | `pytest tests packages` | **PASS** — 100 passed, 79 skipped |
| Core tests | `pytest packages/core` | **PASS** — 75 passed |
| Web tests | `pnpm --filter @nachtlabs/web test` | **PASS** — 71 passed, 6 files |
| Native shell orchestration | `pytest tests/native` | **PASS** — 16 passed, 4 skipped |
| Type check | `make typecheck` (mypy strict, tsc) | **PASS** — 56 files, no issues |
| Lint | `make lint` (ruff, eslint) | **PASS** |
| Format | `make format-check` (ruff, Prettier) | **PASS** — 87 files formatted |
| Build | `make build` | **PASS** — Next.js production build compiled |
| API client drift | `make api-client-check` | **PASS** — no drift vs. live app |
| E2E collection | `playwright test --list` | 48 tests collected; **not executed** |

`make api-client-check` regenerates the schema and compares byte-for-byte. It passed, so
`docs/api/openapi.json` and `packages/api-client/src/generated.d.ts` match the live
FastAPI application. It was run against disposable placeholder credential files outside
the repository; no real credential was used and none was written to the tree.

## Container deployment (added later the same day)

`compose.yaml` runs the control plane: API, worker, interface and PostgreSQL 16. The executor is
deliberately absent — [ADR 0006](../adr/0006-container-deployment.md) records why its isolation
primitives have no container equivalent, and [container deployment](../operations/container-deployment.md)
is the operator runbook.

Executed against Docker Engine 29.7.2 with Compose v5.4.0 on this WSL2 host:

| Check | Result |
|---|---|
| Image builds (`Dockerfile.api`, `Dockerfile.web`) | **PASS** — pinned Python 3.12 / Node 24.21.0 / pnpm 10.0.0 / uv 0.12.19 |
| Full stack startup and ordering | **PASS** — init → postgres → roles → migrate → schematest → grants → api/worker/web, all `depends_on` conditions honoured |
| `/api/v1/health/ready` through the interface | **PASS** — `{"status":"ready","schema":"0003"}` |
| Setup page served | **PASS** — first-run Owner form renders at `/setup` |
| Worker heartbeat, no tick failures | **PASS** |
| **Integration suite** | **PASS — 76 passed, 1 skipped** (previously all skipped for want of a database) |
| Ollama reachable from a container | **PASS** — the operator's LAN endpoint in 0.06s, 9 models |
| Ollama through the app's pinned transport | **PASS** — `PinnedJSON` discovery from inside the network |
| Generated secrets absent from images | **PASS** — master key and bootstrap token in no image layer |
| Operator's own address absent from the working tree | **PASS** after replacing it in one test file |

Five defects were found and fixed while building this, all of them silent rather than loud:

1. **`uv sync` installed the workspace editable**, so the runtime image imported from the
   builder's `/src`, which does not exist in the final stage. Fixed with `--no-editable`.
2. **A global `ARG` is invisible inside a build stage.** Using it without re-declaring produced an
   *empty* value, so the interface's API proxy rewrite compiled to `/api/:path*` — the API
   rewriting to itself. The interface served pages and could not reach the API, with nothing in
   the logs explaining why.
3. **Next's rewrite proxy forwards the upstream hostname** in the `Host` header, so the API
   received `api:8000` and `TrustedHostMiddleware` rejected it: a 400 with no route matched.
   Fixed by permitting the internal service name alongside the public one.
4. **Generated files were `root:root`**, so the non-root service account could not read its own
   configuration. Fixed by group-owning the files and the directories, at the modes the systemd
   units already use.
5. **The integration fixture's `TRUNCATE` needs table ownership**, which the application role
   deliberately lacks. Granted to the `_test` database only; the application database still has no
   way to remove audit history wholesale.

## End-to-end suite (executed the same day, against the container stack)

The 48 Playwright tests had never been run. Run against a freshly initialised
container deployment at `http://localhost:3035`, they exposed **eight failures — six
of them defects in the tests themselves and two real product bugs.**

| Check | Result |
|---|---|
| `pnpm test:e2e` against the container stack | **PASS — 50 passed** (48 pre-existing + 2 added) |

Product bugs found and fixed:

1. **`/` sent a signed-out visitor to the private overview before the 401 landed.**
   `signedOut` is derived from the `401` on `/auth/me`, so on the first render it is
   false for *everyone*. The `/` → `/overview` rule therefore matched an anonymous
   visitor, and because the redirect is a `useEffect` the wrong hop was committed and
   visible; the sign-in rule only corrected it on a second navigation. Fixed by
   requiring the identity check to have settled before either the `/` jump or the
   sign-in redirect. `apps/web/src/components/screen.tsx:47-99`.
2. **Two E2E specs hardcoded port 3000 as "the address in the browser"**, so against a
   container on 3035 the mock claimed an origin the browser was not using and six
   tests failed while the application behaved correctly. Both now derive the origin
   from `NACHTLABS_E2E_URL`.

Test defects fixed (each was asserting something the code never promised):

- `mockProvider` accepted only `https://`, so the "accepted once the installation
  permits cleartext" case could never reach the step it asserted on. It now mirrors
  the server's actual rule and reports the saved connection, so the wizard advances.
- Two tests called `.check()` on Yes/No `<select>` elements and threw *Not a
  checkbox or radio button* before reaching their assertion. Left to the default,
  which is already the permissive value.
- One test expected the "only accepted for loopback" wording while the form's default
  selected the other, equally correct branch. Both are now covered separately.
- The Secure-cookie banner test permitted the address the browser was on and then
  expected the mismatch banner, which the two conditions cannot both satisfy.

The **first** E2E run in this project's history therefore closed 40/48 and the
twentieth is 50/50. `next-env.d.ts` was also untracked during this work: `next dev`
and `next build` write different content to it, so a host that had ever built had a
permanently dirty tree and `update.sh` and `reset-first-run.sh` both refused to run.

## Security and dependency scans (executed 2026-09-28)

`make secret-scan` and `make dependency-audit` had never been run; both needed a pinned
`gitleaks` and network access.

| Check | Result |
|---|---|
| `make secret-scan` (gitleaks 8.30.1, pinned + checksum verified) | **PASS — no leaks** |
| `make dependency-audit` (pip-audit) | **PASS** — no runtime advisories; 1 dev-only ID ignored by name |
| `make dependency-audit` (pnpm audit --audit-level high) | **PASS** — 2 moderate, 0 high |

`gitleaks` was verified in both directions before being trusted: a planted high-entropy
key in the tree was reported as `generic-api-key`, and removing it returned the scan to
clean. Its 9 default findings were all inside `.next/`, which `config/gitleaks.toml`
allowlists as generated output.

**Fixed.** `pip-audit` reported nine advisories against `cryptography` 46.0.7, seven of
which are fixed in 48.0.1 or later, including one in the OpenSSL bundled with the wheel.
The dependency is direct in `packages/core/pyproject.toml` and bounded `<47`, so the fixes
were unreachable. The bound is now `<51` and the lock is resolved at 50.0.1. Only the AEAD
interface is used (`AESGCM`, for stored secrets and evidence), which is unchanged across
these majors, and the 76 integration tests — which encrypt and decrypt throughout — pass
against it.

**Accepted by name, not by omission.** The gate ignores exactly one advisory ID,
`PYSEC-2026-1845` against `pytest` <9.0.3, which is dev-group only and never installed in
the runtime image. It is ignored by ID rather than by package so a *new* advisory in a dev
tool still fails the job, and the reason and the removal condition are recorded in the
Makefile. `pnpm audit` reports two moderate advisories in `vitest` and `@vitest/mocker`,
also development-only; the patched line is vitest 4, a major-version migration of the test
runner that is not a proportionate response to a test-time path-traversal advisory. That is
recorded here as a deliberate deferral rather than left to look like an oversight.

## Continuous integration

`.github/workflows/checks.yml` runs five independent jobs on every push and pull request:
Python lint/types/unit, web lint/types/test/format, a generated-client drift check, the
integration suite against a real PostgreSQL 16, and the secret plus dependency scans. Each
gate in it was executed locally before being wired up, and the version pins match the ones
`package.json` engines and the Dockerfiles require. The executor is not exercised, because
its isolation cannot be validated anywhere but a bare-metal host and a CI runner is not one.

## Still NOT RUN

These require infrastructure or operator authorization that was not available here, and
they are the checks that actually matter for deployment:

- The 4 `tests/native/test_executor_boundary.py` tests — skipped by design; they require
  explicit operator opt-in on a disposable Linux qualification host.
- All systemd, executor qualification, backup/restore, key rotation and incident rows in
  `docs/planning/acceptance-matrix.md`.

No acceptance row is marked passed from this pass. The source is in a demonstrably
cleaner state than the documents claimed, but runtime deployment remains unverified.

## End-to-end suite, re-run after the pinned-address change

`pnpm test:e2e` passes 49 of 50 against the running container stack. The single skip is
`governance.spec.ts`, which signs in as a real Owner and skips only when
`NACHTLABS_E2E_EMAIL` is unset. On an installation an operator has already initialised,
either supply a disposable account to run it or accept the skip. A stale credential for an
account that no longer exists fails rather than skipping, which is the intended behaviour.

A run with credentials for an account removed by a reinitialisation reports failures that
have nothing to do with the code under test. The distinction matters: it was traced to the
absent account before the pin change was cleared, and reproduced with the change stashed
out, rather than being assumed from a green-looking count.

## Provider egress, and two defects that hid a feature behind a policy message

An operator could not reach Step 3. The interface reported provider checks as
disabled by policy, which was true, but the documented way to enable it did
nothing, so the message was not the whole of the problem.

1. `container-init.py` hard-coded `NACHTLABS_INTEGRATION_NETWORK_ENABLED=false`,
   and `compose.yaml` also passed it in `environment:`. `with-env.sh` sources
   the generated file *after* compose sets the container environment, so the
   compose value was silently discarded. The runbook documented the compose
   variable, so the advertised procedure had never worked. Verified directly:
   compose passed `true`, sourcing the file overwrote it with `false`, and
   `network_allowed("ollama")` reported `False`.
2. `compose.yaml` named no build target, and the last stage in `Dockerfile.api`
   is `test`, which carries the dev group and no `postgresql-client`. Any
   `docker compose build` therefore tagged the wrong artifact as the service
   image. It failed late and misleadingly: api, worker and migrations started,
   and only the roles step died with `psql: command not found`.

The first was masked because the wizard's instruction was to edit
`/etc/nachtlabs/api.env`, a path inside a named volume the host cannot see. The
second was masked because the previously started roles container was reused
until a compose change forced it to be recreated.

The switches are now recorded by `container-init.py` and absent from the compose
`environment:` block; `NACHTLABS_REWRITE_CONFIG=true` updates the operator
allowlist on an install that already started, which is what makes the documented
change followable without discarding the volume. `NACHTLABS_INTEGRATION_CA_FILE`
was given the same treatment: the wizard told operators to set it, and it was in
neither the generated files nor compose, so there had been no supported way.

Both compose defects now have tests, and the tests were confirmed to fail when
the defects are reintroduced. That check mattered: the first version of the
shadowing test derived its key set by parsing a dict literal that the switches
now reach through a splat, so it compared against an empty set and passed while
the defect was present. It reads the generated files now.

### What the full gate does and does not cover

`make test` is unit tests plus web tests and never touches a running container.
`pnpm test:e2e` against the container stack is the only thing that exercises a
built image, and it found 9 failures that no earlier check had: the E2E tests
still filled the pinned-IP field, which is correctly read-only now that a
numeric origin derives it. Those tests had been passing only because the
deployed bundle was stale. They assert the derived value now, which also covers
the derivation.

E2E: 49 passed, 1 skipped. The skip is `governance.spec.ts`, which signs in as a
real Owner and skips only when `NACHTLABS_E2E_EMAIL` is unset.
