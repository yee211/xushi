"""Expose sync execution progress without retaining school credentials."""
from alembic import op

revision = "0017_sync_progress"
down_revision = "0016_audit_repairs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS phase TEXT NOT NULL DEFAULT 'queued'")
    op.execute("ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE academic_sync_jobs DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE academic_sync_jobs DROP COLUMN IF EXISTS phase")
