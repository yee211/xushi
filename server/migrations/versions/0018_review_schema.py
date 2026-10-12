"""Reconcile runtime schema with historical admin and academic migrations."""
from alembic import op

revision = "0018_review_schema"
down_revision = "0017_sync_progress"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE academic_bindings ALTER COLUMN user_id TYPE BIGINT")
    op.execute("ALTER TABLE admins ALTER COLUMN username TYPE VARCHAR(80)")
    op.execute("ALTER TABLE admins ALTER COLUMN role TYPE VARCHAR(32)")
    op.execute("ALTER TABLE admins ALTER COLUMN created_by TYPE VARCHAR(80)")
    op.execute("ALTER TABLE admins ALTER COLUMN created_by SET DEFAULT ''")
    op.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
    op.execute("CREATE INDEX IF NOT EXISTS admins_username_idx ON admins(username)")


def downgrade():
    # Widening is intentionally retained: narrowing could truncate user data.
    pass
