"""Associate channel identities with the account that receives their messages.

Revision ID: 0006_identity_account
Revises: 0005_daily_push
"""
from alembic import op

revision = "0006_identity_account"
down_revision = "0005_daily_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_identities ADD COLUMN IF NOT EXISTS account_id VARCHAR(255)")
    op.execute("""UPDATE user_identities u SET account_id=c.account_id
        FROM channel_accounts c
        WHERE u.provider='weixin_ilink' AND c.provider=u.provider
          AND c.owner_user_id=u.user_id AND c.status='active' AND u.account_id IS NULL""")
    # Older shared-bot deployments did not record ownership. If there is exactly
    # one active account, it is the only safe unambiguous backfill target.
    op.execute("""UPDATE user_identities SET account_id=(
            SELECT account_id FROM channel_accounts
            WHERE provider='weixin_ilink' AND status='active' LIMIT 1)
        WHERE provider='weixin_ilink' AND account_id IS NULL
          AND (SELECT COUNT(*) FROM channel_accounts
               WHERE provider='weixin_ilink' AND status='active')=1""")
    op.execute("CREATE INDEX IF NOT EXISTS user_identities_account_idx ON user_identities(provider,account_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS user_identities_account_idx")
    op.execute("ALTER TABLE user_identities DROP COLUMN IF EXISTS account_id")
