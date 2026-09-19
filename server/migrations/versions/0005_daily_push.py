"""Daily push logs and user identity context_token.

Revision ID: 0005_daily_push
Revises: 0004_adjustment_idempotency
"""
from alembic import op

revision = "0005_daily_push"
down_revision = "0004_adjustment_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS daily_push_logs (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        push_date DATE NOT NULL,
        push_type VARCHAR(32) NOT NULL DEFAULT 'morning_brief',
        status VARCHAR(20) NOT NULL DEFAULT 'done',
        pushed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        error TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (user_id, push_date, push_type)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS daily_push_logs_date_idx ON daily_push_logs(push_date)")
    op.execute("ALTER TABLE user_identities ADD COLUMN IF NOT EXISTS context_token VARCHAR(512) NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE user_identities DROP COLUMN IF EXISTS context_token")
    op.execute("DROP TABLE IF EXISTS daily_push_logs")
