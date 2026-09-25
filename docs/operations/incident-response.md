# Foundation incident response

Use the failing command/request ID and `make logs`. Never return environment/credential files, raw SMTP payloads, cookies, MFA/recovery material or holdout instructions in support output.

DB/schema failure: stop dependent checks, inspect PostgreSQL configuration and Alembic revision with the administrator role; do not switch databases or bypass migrations. Worker failure: inspect unit/grants and heartbeat. SMTP failure: examine job state/attempt/error class. Retries may duplicate a single-use link; no fake delivery success exists.

Revoke compromised API keys and inspect their project/audit history. Lost MFA normally uses a recovery code. If all Owner recovery options are lost, a Linux administrator can run `scripts/recover-owner.py` from the local console with the migration environment loaded. It requires root, explicit email confirmation and a reason. It clears MFA only for an active Owner, revokes sessions/challenges, and appends audit. Optional password reset uses hidden prompts. Organization MFA policy remains enabled and requires re-enrollment. This is exceptional console recovery, not an API bypass.

For broader incidents, stop affected services, preserve allowed evidence, protect encryption/backup keys and test recovery in isolation. No agent/target-repository process exists at this checkpoint.
