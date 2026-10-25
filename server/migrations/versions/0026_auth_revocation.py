"""Durable per-user JWT revocation boundary."""
from alembic import op

revision = "0026_auth_revocation"
down_revision = "0025_user_activity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_revoked_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS auth_revoked_at")
