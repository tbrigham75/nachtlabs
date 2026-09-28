"""Transactional reset/grant check on a separately provisioned disposable DB.

Needs the three real runtime roles and a test administrator allowed to SET ROLE.
No production database, shared application test DB, or role creation is allowed.
"""

import os
import runpy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
maintenance = runpy.run_path(str(ROOT / "scripts/maintenance_db.py"))


def test_reset_restores_runtime_permissions() -> None:
    credential = os.environ.get("NACHTLABS_MAINTENANCE_TEST_DATABASE_URL_FILE")
    if not credential:
        pytest.skip("Provision a separate *_maintenance_test database with runtime roles")
    url = Path(credential).read_text().strip()
    assert (make_url(url).database or "").endswith("_maintenance_test")
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
        try:
            # No commits: the test restores the original schema even on failure.
            # Only an otherwise empty, migrated test database is accepted.
            maintenance["reset_schema"](db, False)
            for revision in ("0001_foundation", "0002_integrations", "0003_factory"):
                db.execute((ROOT / f"apps/api/migrations/versions/{revision}.sql").read_text())
            maintenance["apply_grants"](db, ROOT)
            db.execute("SET LOCAL ROLE nachtlabs_api")
            assert db.execute("SELECT count(*) FROM organizations").fetchone() == (0,)
            # First-account writes must be allowed, beyond simply SELECT access.
            org = uuid4()
            db.execute(
                "INSERT INTO organizations (id,created_at,singleton,name,require_admin_mfa,version) "
                "VALUES (%s,now(),1,'Reset test',false,1)",
                (org,),
            )
            db.execute(
                "INSERT INTO users (id,created_at,org_id,email,name,role,password_hash,"
                "active,theme,mfa_last_step,recovery_hashes,version) "
                "VALUES (%s,now(),%s,%s,'Owner','owner','test-only-hash',true,'midnight',0,'[]',1)",
                (uuid4(), org, "reset@example.com"),
            )
            db.execute("RESET ROLE")
            db.execute("SET LOCAL ROLE nachtlabs_worker")
            db.execute("SELECT * FROM mail_jobs LIMIT 1")
            db.execute("UPDATE mail_jobs SET state = state WHERE false")
            db.execute("RESET ROLE")
            db.execute("SET LOCAL ROLE nachtlabs_executor")
            db.execute("SELECT * FROM executor_jobs LIMIT 1")
            db.execute("RESET ROLE")
            # Restoring access must preserve immutable evidence restrictions.
            assert db.execute(
                "SELECT has_table_privilege('nachtlabs_api','audit_events','DELETE')"
            ).fetchone() == (False,)
            assert db.execute(
                "SELECT has_table_privilege('nachtlabs_worker','run_evidence','UPDATE')"
            ).fetchone() == (False,)
        finally:
            db.rollback()
