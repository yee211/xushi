"""Persistent batches for refreshing saved peer timetables."""
from alembic import op

revision = "0024_other_sync_jobs"
down_revision = "0023_academic_others"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS academic_other_sync_jobs (
        id UUID PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'queued', items JSONB NOT NULL,
        lease_token UUID, leased_until TIMESTAMPTZ,
        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_other_jobs_active_user ON academic_other_sync_jobs(user_id)
        WHERE state IN ('queued','running')""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_other_jobs_user_created
        ON academic_other_sync_jobs(user_id, created_at DESC)""")


def downgrade():
    op.execute("DROP TABLE academic_other_sync_jobs")
