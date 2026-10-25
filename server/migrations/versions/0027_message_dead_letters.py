"""Durable isolation and replay for exhausted inbound messages."""
from alembic import op

revision = "0027_message_dead_letters"
down_revision = "0026_auth_revocation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS channel_message_dead_letters (
    provider VARCHAR(32) NOT NULL,account_id VARCHAR(255) NOT NULL,message_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,error TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMPTZ,
    PRIMARY KEY(provider,account_id,message_id))""")


def downgrade():
    op.execute("UPDATE channel_messages SET status='failed' WHERE status='dead_letter'")
    op.execute("DROP TABLE IF EXISTS channel_message_dead_letters")
