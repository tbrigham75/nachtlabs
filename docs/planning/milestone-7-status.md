# Milestone 7: Validation and independent review

Source authored on 2026-09-25. **All execution checks: NOT RUN.** Continued under the operator’s authorization to code all milestones without pausing for testing.

## Added
Candidate hash binds contents and executable bits; required catalog-backed Journey checks; protected holdout inputs; human attestations; fresh verifier workspace; strict verdict/criteria binding; bounded replanning; optional Owner warning acceptance.

## Source map
execution/files.py and stages.py; workflows/engine.py and exceptions.py; workflow_routes.py; factory evidence UI. Core paths are under packages/core/src/nachtlabs; routes under apps/api/src/nachtlabs_api.

## Deferred operator checks
Symlink/hardlink/traversal rejection; altered candidate; missing/failed check; protected input leakage; unauthorized attestation; verifier mutation; missing criterion; expired Owner exception; retry exhaustion.

Run the applicable make test, make test-integration, make test-e2e, make lint, make typecheck, make build, make migration-check and make secret-scan commands only on the operator’s Linux testing pass. Native security/provider checks additionally require the qualification procedure. No commands in this list were executed during authoring.

## Operator values
Catalog command names for all automated Journeys, protected version-to-command mapping, independent verifier profile, optional warning-exception policy.

## Handoff
Follow [the full Linux handoff](../operations/milestone-10-handoff.md) and [current limitations](milestone-10-status.md). No commits or remote Git operations were performed. This source report does not close runtime acceptance.
