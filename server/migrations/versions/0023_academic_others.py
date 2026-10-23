"""Saved timetables belonging to other students."""
from alembic import op

revision = "0023_academic_others"
down_revision = "0022_sync_request_ids"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS academic_others (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        student_id TEXT NOT NULL, term TEXT NOT NULL, remark TEXT NOT NULL DEFAULT '',
        snapshot JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,student_id))""")


def downgrade():
    op.execute("DROP TABLE academic_others")
