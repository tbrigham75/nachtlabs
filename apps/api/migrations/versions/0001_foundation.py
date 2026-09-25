"""Immutable Checkpoint A schema snapshot; do not import current application metadata."""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    raise RuntimeError("Initial schema downgrade is destructive. Restore an isolated backup instead.")
