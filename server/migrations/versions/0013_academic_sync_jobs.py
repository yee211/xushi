"""Durable school sync jobs and midnight deduplication."""
from alembic import op

SCHEMA = ("CREATE TABLE IF NOT EXISTS academic_sync_jobs (\n        id UUID PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n        student_id TEXT NOT NULL,binding_revision BIGINT NOT NULL,binding_updated_at TIMESTAMPTZ NOT NULL,\n        term TEXT NOT NULL,refresh BOOLEAN NOT NULL DEFAULT FALSE,source TEXT NOT NULL DEFAULT 'manual',\n        state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),\n        attempts INTEGER NOT NULL DEFAULT 0,result JSONB,error TEXT,\n        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,\n        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,\n        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)", "CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_jobs_active_user ON academic_sync_jobs(user_id)\n        WHERE state IN ('queued','running')", 'CREATE INDEX IF NOT EXISTS idx_academic_jobs_pending ON academic_sync_jobs(state,available_at,created_at)', 'CREATE TABLE IF NOT EXISTS academic_sync_control(id INTEGER PRIMARY KEY CHECK(id=1),pause_until TIMESTAMPTZ)', 'INSERT INTO academic_sync_control(id) VALUES(1) ON CONFLICT DO NOTHING', 'CREATE TABLE IF NOT EXISTS academic_sync_days(run_date DATE PRIMARY KEY,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)')

revision = "0013_academic_sync_jobs"
down_revision = "0012_academic_binding"
branch_labels = None
depends_on = None


def upgrade():
    for sql in SCHEMA:
        op.execute(sql)


def downgrade():
    op.execute("DROP TABLE IF EXISTS academic_sync_jobs")
    op.execute("DROP TABLE IF EXISTS academic_sync_days")
    op.execute("DROP TABLE IF EXISTS academic_sync_control")
