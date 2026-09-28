"""Database operations for the root-console maintenance scripts.

Credentials are read from a protected file, never passed in process arguments.
All failures exit nonzero without printing connection strings or SQL parameters.
"""

import argparse
import os
from pathlib import Path

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

TABLES = (
    "organizations",
    "users",
    "runs",
    "run_evidence",
    "audit_events",
    "identity_tokens",
    "integration_connections",
)


def require_reconciled(db: psycopg.Connection) -> None:
    unresolved = db.execute(
        "SELECT count(*) FROM executor_jobs WHERE state IN ('claimed','running','uncertain')"
    ).fetchone()
    if unresolved is None or unresolved[0] != 0:
        raise RuntimeError("Stop and reconcile outstanding executor jobs before maintenance")


def inspect_activity(db: psycopg.Connection, force: bool) -> None:
    require_reconciled(db)
    counts = {}
    for table in TABLES:
        # Table names are fixed source constants, never operator input.
        row = db.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()
        if row is None:
            raise RuntimeError("Cannot determine stored activity")
        counts[table] = row[0]
        print(f"  {table:24}: {row[0]}")
    if not force and (
        counts["runs"]
        or counts["run_evidence"]
        or counts["integration_connections"]
        or counts["audit_events"] > 2
    ):
        raise RuntimeError("Recorded activity exists; use --force only to discard it deliberately")


def check_migrations(db: psycopg.Connection, root: Path) -> None:
    heads = set(ScriptDirectory.from_config(Config(str(root / "apps/api/alembic.ini"))).get_heads())
    applied = {row[0] for row in db.execute("SELECT version_num FROM alembic_version")}
    if not heads or applied != heads:
        raise RuntimeError(
            "Database revision differs from the target release. Review and apply migrations "
            "and grants with services stopped, then rerun the update."
        )


def reset_schema(db: psycopg.Connection, force: bool) -> None:
    # Caller must stop writers and hold the broker lock for the whole reset.
    inspect_activity(db, force)
    db.execute("DROP SCHEMA public CASCADE")
    db.execute("CREATE SCHEMA public")
    db.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")


def apply_grants(db: psycopg.Connection, root: Path) -> None:
    db.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    db.execute("GRANT USAGE ON SCHEMA public TO nachtlabs_api,nachtlabs_worker,nachtlabs_executor")
    source = (root / "scripts/grants.sql").read_text()
    # This repository file is SQL with one psql error-handling directive. Refuse
    # other metacommands rather than silently interpreting an expanded script.
    lines = []
    for line in source.splitlines():
        if line.strip() == r"\set ON_ERROR_STOP on":
            continue
        if line.lstrip().startswith("\\"):
            raise RuntimeError("Unsupported grants metacommand")
        lines.append(line)
    db.execute("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["inspect", "reset", "grants", "check-migrations", "reconciled"]
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        credential = Path(os.environ["NACHTLABS_MIGRATION_DATABASE_URL_FILE"])
        url = credential.read_text().strip().replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(
            url,
            connect_timeout=10,
            options="-c lock_timeout=10000 -c statement_timeout=60000",
        ) as db:
            if args.action == "inspect":
                inspect_activity(db, args.force)
            elif args.action == "reset":
                # Recheck within the same transaction as deletion, after the
                # caller has stopped every writer and acquired the broker lock.
                reset_schema(db, args.force)
            elif args.action == "grants":
                apply_grants(db, args.root)
            elif args.action == "reconciled":
                require_reconciled(db)
            else:
                check_migrations(db, args.root)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit(
            "Database maintenance failed; check configuration, database access and schema. "
            "No success was recorded."
        ) from None


if __name__ == "__main__":
    main()
