"""Add admin console, request logs, and llm config tables, and alter feedback table.

Revision ID: 0009_admin_console
Revises: 0008_feedback
"""
from alembic import op

revision = "0009_admin_console"
down_revision = "0008_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. feedbacks table enhancements
    op.execute("ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS admin_note TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
    op.execute("CREATE INDEX IF NOT EXISTS feedbacks_user_created_idx ON feedbacks(user_id, created_at DESC)")

    # 2. admins
    op.execute("""CREATE TABLE IF NOT EXISTS admins (
        id BIGSERIAL PRIMARY KEY,
        username VARCHAR(64) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'admin',
        created_by VARCHAR(64) NOT NULL DEFAULT 'system',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    # 3. admin_audit_logs
    op.execute("""CREATE TABLE IF NOT EXISTS admin_audit_logs (
        id BIGSERIAL PRIMARY KEY,
        admin_name VARCHAR(64) NOT NULL,
        action VARCHAR(64) NOT NULL,
        target_type VARCHAR(64) NOT NULL,
        target_id VARCHAR(120) NOT NULL DEFAULT '',
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS admin_audit_created_idx ON admin_audit_logs(created_at DESC)")

    # 4. api_request_logs
    op.execute("""CREATE TABLE IF NOT EXISTS api_request_logs (
        id BIGSERIAL PRIMARY KEY,
        method VARCHAR(10) NOT NULL,
        path VARCHAR(255) NOT NULL,
        status SMALLINT NOT NULL,
        duration_ms INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS api_request_logs_created_idx ON api_request_logs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS api_request_logs_path_created_idx ON api_request_logs(path, created_at DESC)")

    # 5. llm_configs
    op.execute("""CREATE TABLE IF NOT EXISTS llm_configs (
        scope VARCHAR(32) PRIMARY KEY,
        base_url VARCHAR(500) NOT NULL DEFAULT '',
        api_key_encrypted TEXT NOT NULL DEFAULT '',
        model VARCHAR(120) NOT NULL DEFAULT '',
        timeout_seconds NUMERIC(5,2) NOT NULL DEFAULT 30,
        max_tokens INTEGER NOT NULL DEFAULT 1000,
        enable_thinking BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS llm_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS api_request_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS admin_audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS admins CASCADE")
    op.execute("ALTER TABLE feedbacks DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE feedbacks DROP COLUMN IF EXISTS admin_note")
