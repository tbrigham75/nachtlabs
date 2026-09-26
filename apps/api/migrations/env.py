import os
from pathlib import Path

from alembic import context
from nachtlabs.models import Base
from sqlalchemy import create_engine, pool

credential = os.environ.get("NACHTLABS_MIGRATION_DATABASE_URL_FILE")
if not credential:
    raise RuntimeError("Set NACHTLABS_MIGRATION_DATABASE_URL_FILE for the migration role")
url = Path(credential).read_text().strip()
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("PostgreSQL is required")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool, hide_parameters=True).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
