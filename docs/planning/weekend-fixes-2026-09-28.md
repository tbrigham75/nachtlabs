# Weekend review fixes — 2026-09-28

Status: source changes and regression checks authored. All execution checks NOT RUN.
The user approved the six-part fix plan; the source-only working agreement remains in force.

## Implemented scope

1. Reset restores schema usage and the existing least-privilege table grants before startup.
2. Reset refuses failed/unknown shutdown, live executor units, unresolved executor jobs and failed
   activity queries. The broker and maintenance locks are held across the operation. Database reset
   is transactional and rechecks activity after writers have stopped.
3. LLM setup refreshes readiness after profile writes, polls it while discovery is pending, exposes
   the next step after discovery, checks duplicate model choices, and explicitly opens the summary.
4. Missing connections render a prerequisite message instead of dereferencing null; Summary only
   reports completion when readiness says complete.
5. Reauthentication resets prior confirmation, preserves the interrupted non-secret form, clears
   its interruption notice, and returns to that step. Repeated expiry can be confirmed again.
6. Update prepares an isolated release before downtime, compares actual database revisions to the
   target, snapshots the stopped release, and retains a standalone recovery procedure after failure.

## Authored regression coverage

- `apps/web/tests/llm-setup.test.tsx`: complete flow without reload; worker completion; distinct
  models; empty-state tabs; incomplete summary; two successive reauthentication interruptions.
- `tests/test_maintenance_db.py`: unknown activity and unresolved execution never reach deletion;
  force does not bypass executor reconciliation; repeated attempts cannot bypass schema checks.
- `tests/native/test_maintenance_scripts.py`: Linux shell orchestration in temporary directories
  with fake service, package-manager, Git and database commands. Covers shutdown failures, failed
  grant restoration, fetch/dependency/build/schema failures before downtime, activation recovery,
  interruption before a snapshot, and successful bundle promotion. No real host services or remote
  operations are used by these fixtures.
- `tests/integration/test_maintenance_permissions.py`: transactional schema reset and actual API,
  worker and executor role permissions on a separate `*_maintenance_test` database. Confirms
  first-account table writes and immutable evidence restrictions. The transaction is rolled back.

## Operator execution on Linux

Run in a disposable development checkout with installed dependencies, never the production tree:

    uv run --no-sync pytest tests/test_maintenance_db.py tests/native/test_maintenance_scripts.py
    pnpm --filter @nachtlabs/web test
    make typecheck
    make lint
    make format-check
    make build

For the permission integration check, provision a separate, otherwise empty database whose name
ends in `_maintenance_test`, migrate it to 0003, and provision the three real runtime roles. Use a
test administrator permitted to SET ROLE and to recreate that database's public schema. Set
`NACHTLABS_MAINTENANCE_TEST_DATABASE_URL_FILE` to its protected SQLAlchemy credential file, then:

    uv run --no-sync pytest tests/integration/test_maintenance_permissions.py

The test never creates cluster roles or commits its schema changes. Do not point it at the normal
application integration database; the suffix guard is intentionally more specific.

On an isolated installed Linux deployment, also verify the full reset -> Owner setup -> worker
heartbeat path with separate runtime credentials, a full model wizard flow with the worker running,
and update/recovery with a deliberately interrupted activation. After a schema mismatch, verify a
second update still refuses until the target migration is actually applied. Record commands,
results and any host-specific failures here before claiming runtime acceptance.

No builds, tests, linters, type checks, format checks, migrations, services, network probes or remote
Git operations were executed during this change. No commit was created.
