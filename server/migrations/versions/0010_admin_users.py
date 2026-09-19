"""Multiple admin accounts management.

Revision ID: 0010_admin_users
Revises: 0009_admin_console
"""
from alembic import op

revision = "0010_admin_users"
down_revision = "0009_admin_console"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS admins (
        id BIGSERIAL PRIMARY KEY,
        username VARCHAR(80) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'admin',
        created_by VARCHAR(80) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS admins_username_idx ON admins(username)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admins")
