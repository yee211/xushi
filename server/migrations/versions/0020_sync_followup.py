"""Persist typed post-sync query plans and their delivery payloads."""
from alembic import op

revision = "0020_sync_followup"
down_revision = "0019_sync_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE academic_sync_notifications ADD COLUMN IF NOT EXISTS followup JSONB")
    op.execute("ALTER TABLE academic_sync_notifications ADD COLUMN IF NOT EXISTS delivery_text TEXT")


def downgrade():
    op.execute("ALTER TABLE academic_sync_notifications DROP COLUMN IF EXISTS delivery_text")
    op.execute("ALTER TABLE academic_sync_notifications DROP COLUMN IF EXISTS followup")
