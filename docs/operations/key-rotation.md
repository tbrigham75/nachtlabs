# Credential and encryption-key rotation

## Provider tokens

The credential API is write-only. Replace a connection's entire token/webhook-secret bundle using its current expected_version; blank/omitted fields are not silently retained. The version increments and earlier discovery evidence becomes stale. Local revoke deletes the encrypted bundle. Neither action revokes a token at its provider: do that separately in an authorized environment.

Changing origin/IP/private/HTTP settings clears credentials. Do not restore a token to a different destination without checking who controls it.

## Master key: offline Linux maintenance

Not executed during authoring. Use a disposable installation first, with a verified encrypted pre-rotation backup and access to the old key. Stop API, worker, web and executor, and prevent other writers. Use the migration-role environment in a root shell, with all NACHTLABS variables exported:

```bash
set -a
source /etc/nachtlabs/migration.env
set +a
/opt/nachtlabs/.venv/bin/python /opt/nachtlabs/scripts/rotate-master-key.py \
  --new-key-id v2 \
  --new-key-file /etc/nachtlabs/credentials/master-key-v2 \
  --previous-keys-file /etc/nachtlabs/credentials/previous-keys-v2.json \
  --services-stopped
```

Use new names each time. The script refuses existing files, writes new/retained keys first, then locks ciphertext tables and rewraps MFA, pending MFA, holdouts, queued mail, integration credentials, run evidence and executor results in one DB transaction. It records an audit event and prints only paths/IDs.

After a confirmed commit, update NACHTLABS_MASTER_KEY_FILE, NACHTLABS_MASTER_KEY_ID and NACHTLABS_PREVIOUS_MASTER_KEYS_FILE in API, worker, executor and migration env files to the printed values. All processes need the same active key. Generated files use root:nachtlabs-secrets 0640; the enclosing directories must remain protected.

If interrupted, keep services stopped. A database commit may have happened before output was printed. Inspect encryption.rotated audit and ciphertext key-ID prefixes using local migration-role administration, without printing ciphertext/plaintext. If commit occurred, finish configuration; if it did not, retain the original configuration. Do not rerun blindly, delete recovery files or overwrite the old key.

Restart only with consistent configuration. Verify every encrypted data category and restore a new encrypted snapshot into an alternate database. Retain old keys for backups until an explicit retention decision. Restoring the pre-rotation DB requires its corresponding old key; changing a key file alone does not rotate ciphertext.
