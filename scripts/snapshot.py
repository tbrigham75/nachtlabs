"""Encrypted database/key snapshots. Operator-run only; stop services during rotation/backup."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["backup", "restore"])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--target-database")
    parser.add_argument("--key-output", type=Path)
    parser.add_argument("--previous-keys-output", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    url = Path(os.environ["NACHTLABS_MIGRATION_DATABASE_URL_FILE"]).read_text().strip()
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    source_db = unquote(parts.path.lstrip("/"))
    target_db = args.target_database if args.mode == "restore" else source_db
    if not target_db:
        raise SystemExit("A database name is required")
    pg = {**os.environ, "PGHOST": parts.hostname or "127.0.0.1", "PGPORT": str(parts.port or 5432),
          "PGUSER": unquote(parts.username or ""), "PGPASSWORD": unquote(parts.password or ""), "PGDATABASE": target_db}
    with tempfile.TemporaryDirectory(prefix="nachtlabs-snapshot-") as directory:
        temp = Path(directory)
        if args.mode == "backup":
            with psycopg.connect(host=pg["PGHOST"], port=pg["PGPORT"], user=pg["PGUSER"], password=pg["PGPASSWORD"], dbname=target_db) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version_num FROM alembic_version")
                    row = cursor.fetchone()
                    if row is None or row[0] != "0003":
                        raise SystemExit("Apply schema 0003 before using this snapshot format")
            recipient = os.environ.get("NACHTLABS_BACKUP_RECIPIENT", "")
            if not recipient or recipient.startswith("<"):
                raise SystemExit("Set an age public recipient; plaintext backups are not supported")
            output_dir = Path(os.environ.get("NACHTLABS_BACKUP_DIR", "/var/backups/nachtlabs"))
            output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            archive = output_dir / (datetime.now(UTC).strftime("nachtlabs-%Y%m%dT%H%M%S-") + str(uuid4()) + ".tar.age")
            subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(temp / "database.dump")], env=pg, check=True)
            shutil.copyfile(os.environ["NACHTLABS_MASTER_KEY_FILE"], temp / "master-key")
            previous = os.environ.get("NACHTLABS_PREVIOUS_MASTER_KEYS_FILE")
            (temp / "previous-keys.json").write_text(Path(previous).read_text() if previous else "{}")
            (temp / "manifest.json").write_text(json.dumps({"schema": "0003", "format": 2,
                "key_id": os.environ.get("NACHTLABS_MASTER_KEY_ID", "v1"), "created_at": datetime.now(UTC).isoformat()}))
            with tarfile.open(temp / "snapshot.tar", "w") as bundle:
                for name in ("database.dump", "master-key", "previous-keys.json", "manifest.json"):
                    bundle.add(temp / name, arcname=name)
            partial = archive.with_suffix(archive.suffix + ".partial")
            try:
                with partial.open("xb") as output:
                    subprocess.run(["age", "--encrypt", "--recipient", recipient, str(temp / "snapshot.tar")], stdout=output, check=True)
                    output.flush()
                    os.fsync(output.fileno())
                # Same-directory atomic publication: failed age writes cannot masquerade as complete backups.
                os.link(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
            print(f"Encrypted snapshot: {archive}. Restore verification is a separate required step.")
        else:
            if (not args.archive or not args.identity or not args.key_output or not args.previous_keys_output
                    or target_db == source_db or not target_db.endswith("_restore")):
                raise SystemExit("Restore needs archive, age identity, NEW key-output and previous-keys-output paths, and an alternate database ending _restore")
            if args.key_output.exists() or args.previous_keys_output.exists() or args.key_output.resolve() == args.previous_keys_output.resolve():
                raise SystemExit("Refusing to overwrite or overlap key files")
            with psycopg.connect(host=pg["PGHOST"], port=pg["PGPORT"], user=pg["PGUSER"], password=pg["PGPASSWORD"], dbname=target_db) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
                    row = cursor.fetchone()
                    if row is None or row[0] != 0:
                        raise SystemExit("Restore target must be empty")
            with (temp / "snapshot.tar").open("xb") as output:
                subprocess.run(["age", "--decrypt", "--identity", str(args.identity), str(args.archive)], stdout=output, check=True)
            with tarfile.open(temp / "snapshot.tar") as bundle:
                expected = {"database.dump", "master-key", "previous-keys.json", "manifest.json"}
                members = bundle.getmembers()
                if {m.name for m in members} != expected or len(members) != 4 or any(not m.isfile() for m in members):
                    raise SystemExit("Invalid snapshot members")
                for member in members:
                    source = bundle.extractfile(member)
                    assert source is not None
                    with (temp / member.name).open("xb") as output:
                        shutil.copyfileobj(source, output)
            manifest = json.loads((temp / "manifest.json").read_text())
            if manifest.get("schema") != "0003" or manifest.get("format") != 2:
                raise SystemExit("Snapshot schema/format requires a compatible application release")
            # Make keys available before restoring. Failure leaves explicit recovery files and no overwritten original.
            for destination, source_name in ((args.key_output, "master-key"), (args.previous_keys_output, "previous-keys.json")):
                with destination.open("xb") as output:
                    output.write((temp / source_name).read_bytes())
            subprocess.run(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--dbname", target_db, str(temp / "database.dump")], env=pg, check=True)
            print(f"Restored into {target_db}. Configure saved keys and key ID {manifest['key_id']}; apply runtime grants and verify the isolated installation.")


if __name__ == "__main__":
    main()
