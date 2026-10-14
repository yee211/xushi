"""Durable Agent school-sync completion notifications and failure codes."""
from alembic import op

revision = "0019_sync_notifications"
down_revision = "0018_review_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS error_code TEXT')
    op.execute("CREATE TABLE IF NOT EXISTS academic_sync_notifications (\n        id UUID PRIMARY KEY,job_id UUID NOT NULL REFERENCES academic_sync_jobs(id) ON DELETE CASCADE,\n        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n        provider TEXT NOT NULL CHECK(provider='weixin_ilink'),sender_id TEXT NOT NULL,\n        account_id TEXT NOT NULL,message_id TEXT NOT NULL,\n        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sending','sent','failed','cancelled')),\n        attempts INTEGER NOT NULL DEFAULT 0,lease_id UUID,lease_until TIMESTAMPTZ,\n        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,\n        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,sent_at TIMESTAMPTZ,error_code TEXT,\n        UNIQUE(job_id,provider,sender_id,account_id))")
    op.execute('CREATE INDEX IF NOT EXISTS idx_academic_notifications_pending ON academic_sync_notifications(state,available_at)')


def downgrade():
    op.execute("DROP TABLE IF EXISTS academic_sync_notifications")
    op.execute("ALTER TABLE academic_sync_jobs DROP COLUMN IF EXISTS error_code")
