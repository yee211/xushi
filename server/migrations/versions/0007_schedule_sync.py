"""One-time CCSUT schedule sync sessions.

Revision ID: 0007_schedule_sync
Revises: 0006_identity_account
"""
from alembic import op

revision = "0007_schedule_sync"
down_revision = "0006_identity_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS schedule_sync_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), code_hash CHAR(64) NOT NULL UNIQUE,
        submit_token_hash CHAR(64) UNIQUE, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status VARCHAR(24) NOT NULL DEFAULT 'waiting', error_code VARCHAR(40), error_message VARCHAR(240),
        schedule_id BIGINT REFERENCES schedules(id) ON DELETE SET NULL, overwrite_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
        attempt_count SMALLINT NOT NULL DEFAULT 0, expires_at TIMESTAMPTZ NOT NULL,
        exchanged_at TIMESTAMPTZ, consumed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS schedule_sync_user_idx ON schedule_sync_sessions(user_id,created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_sync_sessions")
