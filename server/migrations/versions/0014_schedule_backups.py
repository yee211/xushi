"""School sync recovery points."""
from alembic import op

revision = "0014_schedule_backups"
down_revision = "0013_academic_sync_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS schedule_backups (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_schedule_backups_user ON schedule_backups(user_id,id DESC)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS schedule_backups")
