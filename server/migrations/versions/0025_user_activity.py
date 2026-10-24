"""Track authenticated API and channel activity independently of login refreshes."""
from alembic import op

revision = "0025_user_activity"
down_revision = "0024_other_sync_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_active_at")
