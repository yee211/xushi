"""User feedback and notification queue source.

Revision ID: 0008_feedback
Revises: 0007_schedule_sync
"""
from alembic import op

revision = "0008_feedback"
down_revision = "0007_schedule_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS feedbacks (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        schedule_id BIGINT REFERENCES schedules(id) ON DELETE SET NULL,
        category VARCHAR(24) NOT NULL,
        description VARCHAR(1000) NOT NULL,
        contact VARCHAR(120) NOT NULL DEFAULT '',
        client_info JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS feedbacks_status_created_idx ON feedbacks(status,created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedbacks")
