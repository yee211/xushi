"""Keep sync message idempotency independent of mutable notifications."""
from alembic import op

revision = "0022_sync_request_ids"
down_revision = "0021_message_reply"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS academic_sync_requests (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider TEXT NOT NULL,account_id TEXT NOT NULL,sender_id TEXT NOT NULL,message_id TEXT NOT NULL,
        job_id UUID NOT NULL REFERENCES academic_sync_jobs(id) ON DELETE CASCADE,
        PRIMARY KEY(user_id,provider,account_id,sender_id,message_id))""")
    op.execute("""INSERT INTO academic_sync_requests(user_id,provider,account_id,sender_id,message_id,job_id)
        SELECT user_id,provider,account_id,sender_id,message_id,job_id FROM academic_sync_notifications
        ORDER BY created_at ON CONFLICT DO NOTHING""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS academic_sync_requests")
