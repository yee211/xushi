"""Weixin iLink channel accounts and durable message state.

Revision ID: 0003_weixin_ilink
Revises: 0002_agent_identity
"""
from alembic import op

revision = "0003_weixin_ilink"
down_revision = "0002_agent_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS channel_accounts (
        id BIGSERIAL PRIMARY KEY,
        provider VARCHAR(32) NOT NULL,
        account_id VARCHAR(255) NOT NULL,
        bot_token_encrypted TEXT NOT NULL,
        api_base_url TEXT NOT NULL,
        admin_user_id VARCHAR(255) NOT NULL DEFAULT '',
        owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        update_cursor TEXT NOT NULL DEFAULT '',
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider,account_id))""")
    op.execute("""CREATE TABLE IF NOT EXISTS channel_messages (
        provider VARCHAR(32) NOT NULL,
        account_id VARCHAR(255) NOT NULL,
        message_id VARCHAR(255) NOT NULL,
        status VARCHAR(20) NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        processed_at TIMESTAMPTZ,
        PRIMARY KEY(provider,account_id,message_id))""")
    op.execute("CREATE INDEX IF NOT EXISTS channel_messages_processed_idx ON channel_messages(processed_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channel_messages")
    op.execute("DROP TABLE IF EXISTS channel_accounts")
