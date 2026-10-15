"""Persist generated channel replies before network delivery."""
from alembic import op

revision = "0021_message_reply"
down_revision = "0020_sync_followup"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS reply_text TEXT")


def downgrade():
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS reply_text")
