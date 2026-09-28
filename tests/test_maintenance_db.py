"""Authored maintenance guards; operator execution remains deferred."""

import runpy
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
maintenance = runpy.run_path(str(ROOT / "scripts/maintenance_db.py"))


@pytest.mark.parametrize("force", [False, True])
def test_unreadable_activity_never_reaches_schema_deletion(force: bool) -> None:
    db = MagicMock()
    db.execute.side_effect = psycopg.OperationalError("unavailable")
    with pytest.raises(psycopg.OperationalError):
        maintenance["reset_schema"](db, force)
    assert all("DROP SCHEMA" not in str(call) for call in db.execute.call_args_list)


@pytest.mark.parametrize("force", [False, True])
def test_unreconciled_jobs_cannot_be_forced_away(force: bool) -> None:
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (1,)
    with pytest.raises(RuntimeError, match="reconcile"):
        maintenance["reset_schema"](db, force)
    assert all("DROP SCHEMA" not in str(call) for call in db.execute.call_args_list)


def test_recorded_activity_requires_force() -> None:
    db = MagicMock()
    counts = iter([0, 1, 1, 1, 0, 2, 0, 0])
    db.execute.return_value.fetchone.side_effect = lambda: (next(counts),)
    with pytest.raises(RuntimeError, match="--force"):
        maintenance["reset_schema"](db, False)
    assert all("DROP SCHEMA" not in str(call) for call in db.execute.call_args_list)


def test_migration_check_cannot_be_bypassed_by_repeating_an_update() -> None:
    db = MagicMock()
    db.execute.return_value = [("0002",)]
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Database revision differs"):
            maintenance["check_migrations"](db, ROOT)
    db.execute.return_value = [("0003",)]
    maintenance["check_migrations"](db, ROOT)


def test_migration_check_refuses_missing_version_table() -> None:
    db = MagicMock()
    db.execute.side_effect = psycopg.errors.UndefinedTable("missing")
    with pytest.raises(psycopg.errors.UndefinedTable):
        maintenance["check_migrations"](db, ROOT)
