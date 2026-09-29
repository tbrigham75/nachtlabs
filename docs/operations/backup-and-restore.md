# Encrypted backup and restore

The M4 format contains a PostgreSQL custom dump, active master key, retained-key JSON and schema/key metadata inside an age-encrypted tar. Protect the separate age private identity. Runtime verification has not run: the backup, restore and rotation paths have not been executed against a live database on a native host. Note that the schema must now be 0003, not 0002 — see [upgrade and recovery](upgrade-and-recovery.md).

Stop services and prevent encryption rotation/migrations during a snapshot. In the administrator shell set NACHTLABS_ENV_FILE=/etc/nachtlabs/migration.env, NACHTLABS_BACKUP_DIR and NACHTLABS_BACKUP_RECIPIENT, then invoke make backup. The schema must be 0003: `scripts/snapshot.py` refuses any other revision, because the format records the schema it was taken at and restore rejects a mismatch. Credentials pass to PostgreSQL tools through environment, not process arguments. Temporary plaintext stays in a private directory; protect its storage. The final archive appears only after encryption completes.

For restore, create an EMPTY alternate database ending _restore, owned by the migration identity. Set NACHTLABS_RESTORE_ARCHIVE, NACHTLABS_RESTORE_IDENTITY, NACHTLABS_RESTORE_DATABASE, NACHTLABS_RESTORE_KEY_OUTPUT and NACHTLABS_RESTORE_PREVIOUS_KEYS_OUTPUT. Both key destinations must be new, different paths in protected directories. Invoke make restore.

Unexpected/duplicate/non-file tar members are rejected. Recovery files are saved before pg_restore, which uses one transaction without original ownership/ACLs. Failure may leave recovery files; do not overwrite them blindly. The source/nonempty database is rejected.

Configure the alternate installation with recovered keys/key ID and adjusted permissions, apply grants to its database, and verify identity/MFA, governance/holdouts, integration credential use and audit. Keep provider network switches disabled until permitted. A backup without an exercised restore is not recovery evidence.

The earlier Checkpoint A three-member archive format is not consumed by this script. Use the matching old source for an isolated old-format restore, then migrate to 0002. Never guess an archive format or overwrite the original installation.

M10 extension: schema 0003 database/key snapshots include encrypted workflow evidence and executor results. Candidate files, local mirrors, and delivery journals require the encrypted companion produced by scripts/executor-state.py during the same stopped-service window. Follow upgrade-and-recovery.md; a database-only restore cannot resume execution safely.
