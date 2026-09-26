"""Offline operator-only encryption rotation. Stop services and back up before invoking."""

import argparse
import base64
import grp
import json
import os
import re
import secrets
from pathlib import Path
from uuid import uuid4

from nachtlabs.audit import AuditContext, record
from nachtlabs.database import session
from nachtlabs.factory_models import Evidence, ExecutorJob
from nachtlabs.models import HoldoutContent, IntegrationConnection, MailJob, Organization, User
from nachtlabs.security import decrypt, encrypt_with_key, encryption_keys
from nachtlabs.settings import get_settings
from sqlalchemy import select, text


def protected_file(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    os.fchmod(fd, 0o640)
    os.fchown(fd, 0, grp.getgrnam("nachtlabs-secrets").gr_gid)
    with os.fdopen(fd, "w") as stream:
        stream.write(value + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-key-id", required=True)
    parser.add_argument("--new-key-file", required=True, type=Path)
    parser.add_argument("--previous-keys-file", required=True, type=Path)
    parser.add_argument("--services-stopped", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.services_stopped:
        raise SystemExit(
            "Requires Linux administrator, stopped services, and --services-stopped acknowledgement"
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.new_key_id):
        raise SystemExit("Invalid key ID")
    settings = get_settings()
    if os.environ.get("NACHTLABS_DATABASE_URL_FILE") != os.environ.get(
        "NACHTLABS_MIGRATION_DATABASE_URL_FILE"
    ):
        raise SystemExit("Use the migration role configuration for offline rotation")
    keys = encryption_keys()
    if args.new_key_id in keys:
        raise SystemExit("Choose a new key ID")
    for path in (args.new_key_file, args.previous_keys_file):
        if path.exists() or path.parent.resolve() != Path("/etc/nachtlabs/credentials"):
            raise SystemExit("Choose new file names directly under /etc/nachtlabs/credentials")
    # Save all recovery material before the transaction. On failure retain these files for diagnosis.
    key = secrets.token_bytes(32)
    protected_file(args.new_key_file, base64.b64encode(key).decode())
    protected_file(
        args.previous_keys_file,
        json.dumps(
            {identifier: base64.b64encode(value).decode() for identifier, value in keys.items()}
        ),
    )
    with session() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(9182702)"))
        # Block concurrent ciphertext writes even if an operator mistakenly left a process connected.
        db.execute(
            text(
                "LOCK TABLE users, holdout_contents, mail_jobs, integration_connections, run_evidence, executor_jobs IN ACCESS EXCLUSIVE MODE"
            )
        )

        def rewrap(value: str, context: str) -> str:
            return encrypt_with_key(decrypt(value, context), context, args.new_key_id, key)

        for user in db.scalars(select(User)):
            if user.mfa_secret:
                user.mfa_secret = rewrap(user.mfa_secret, f"mfa:{user.id}")
            if user.mfa_pending:
                user.mfa_pending = rewrap(user.mfa_pending, f"mfa-pending:{user.id}")
        for holdout in db.scalars(select(HoldoutContent)):
            holdout.ciphertext = rewrap(holdout.ciphertext, f"holdout:{holdout.version_id}")
        for mail in db.scalars(select(MailJob).where(MailJob.payload.is_not(None))):
            assert mail.payload is not None
            mail.payload = rewrap(mail.payload, f"mail:{mail.id}")
        for connection in db.scalars(
            select(IntegrationConnection).where(IntegrationConnection.credential.is_not(None))
        ):
            assert connection.credential is not None
            connection.credential = rewrap(connection.credential, f"integration:{connection.id}")
        # Offline migrator can rewrap ciphertext without changing evidence content or hash.
        db.execute(text("ALTER TABLE run_evidence DISABLE TRIGGER immutable_run_evidence"))
        for evidence in db.scalars(select(Evidence)):
            evidence.payload = rewrap(evidence.payload, f"evidence:{evidence.id}")
        db.flush()
        db.execute(text("ALTER TABLE run_evidence ENABLE TRIGGER immutable_run_evidence"))
        for job in db.scalars(select(ExecutorJob).where(ExecutorJob.result.is_not(None))):
            job.result = rewrap(job.result, f"executor:{job.id}")
        record(
            db,
            AuditContext(str(uuid4()), "local-console"),
            "encryption.rotated",
            args.new_key_id,
            actor="local-administrator",
            org_id=db.scalar(select(Organization.id)),
            details={"previous_key_id": settings.master_key_id, "new_key_id": args.new_key_id},
        )
        db.commit()
    print(
        "Ciphertext transaction committed. Before restarting, update ALL API/worker/executor/migration environment files:"
    )
    print(f"NACHTLABS_MASTER_KEY_ID={args.new_key_id}")
    print(f"NACHTLABS_MASTER_KEY_FILE={args.new_key_file}")
    print(f"NACHTLABS_PREVIOUS_MASTER_KEYS_FILE={args.previous_keys_file}")
    print(
        "Keep old keys and the pre-rotation backup until restore acceptance. Do not rerun blindly after interruption."
    )


if __name__ == "__main__":
    main()
