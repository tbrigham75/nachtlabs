"""Durable workflows, restricted execution, evidence and operations."""
from pathlib import Path
from alembic import op
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))

def downgrade() -> None:
    raise RuntimeError("Restore an isolated backup; execution/evidence records are not disposable.")
