"""Agent channel identities, binding codes, and webhook idempotency.

Revision ID: 0002_agent_identity
Revises: 0001_baseline
"""
from alembic import op

revision = "0002_agent_identity"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS user_identities (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider VARCHAR(32) NOT NULL,
        provider_user_id VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider,provider_user_id), UNIQUE(user_id,provider))""")
    op.execute("""CREATE TABLE IF NOT EXISTS identity_binding_codes (
        id BIGSERIAL PRIMARY KEY,
        code_hash CHAR(64) NOT NULL UNIQUE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider VARCHAR(32) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        consumed_at TIMESTAMPTZ,
        attempt_count SMALLINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("CREATE INDEX IF NOT EXISTS binding_codes_user_idx ON identity_binding_codes(user_id,provider)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_binding_codes")
    op.execute("DROP TABLE IF EXISTS user_identities")
