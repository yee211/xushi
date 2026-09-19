"""Make adjustment writes idempotent.

Revision ID: 0004_adjustment_idempotency
Revises: 0003_weixin_ilink
"""
from alembic import op

revision = "0004_adjustment_idempotency"
down_revision = "0003_weixin_ilink"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE course_change_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(80)")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS change_logs_schedule_request_uidx
        ON course_change_logs(schedule_id, request_id) WHERE request_id IS NOT NULL""")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS change_logs_schedule_request_uidx")
    op.execute("ALTER TABLE course_change_logs DROP COLUMN IF EXISTS request_id")
