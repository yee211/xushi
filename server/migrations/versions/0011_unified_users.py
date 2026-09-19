"""Unified users table: email/password (web) + openid (miniprogram) superset.

Revision ID: 0011_unified_users
Revises: 0010_admin_users
"""
from alembic import op

revision = "0011_unified_users"
down_revision = "0010_admin_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧小程序版库的 users(openid NOT NULL)：补邮箱体系三列；旧网页母版库的
    # users(email NOT NULL)：补 openid/last_login_at。均为幂等语句。
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(200)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS openid VARCHAR(128)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_openid_key ON users(openid)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_openid_key")
    op.execute("DROP INDEX IF EXISTS users_email_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS openid")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_hash")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
