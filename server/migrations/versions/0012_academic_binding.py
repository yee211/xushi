"""Shared school associations and sync provenance.

Revision ID: 0012_academic_binding
Revises: 0011_unified_users
"""
from alembic import op

revision = "0012_academic_binding"
down_revision = "0011_unified_users"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS academic_bindings (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        student JSONB NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    op.execute("ALTER TABLE academic_bindings ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE academic_bindings ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ")
    op.execute("ALTER TABLE academic_bindings ADD COLUMN IF NOT EXISTS last_synced_term TEXT")
    op.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS academic_student_id TEXT")
    op.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS academic_snapshot_hash TEXT")
    op.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS academic_synced_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_schedules_academic_identity ON schedules(user_id,academic_student_id,term)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_schedules_academic_identity")
    op.execute("ALTER TABLE schedules DROP COLUMN IF EXISTS academic_synced_at")
    op.execute("ALTER TABLE schedules DROP COLUMN IF EXISTS academic_snapshot_hash")
    op.execute("ALTER TABLE academic_bindings DROP COLUMN IF EXISTS last_synced_term")
    op.execute("ALTER TABLE academic_bindings DROP COLUMN IF EXISTS last_synced_at")
    op.execute("ALTER TABLE academic_bindings DROP COLUMN IF EXISTS revision")
    op.execute("ALTER TABLE schedules DROP COLUMN IF EXISTS academic_student_id")
    op.execute("DROP TABLE IF EXISTS academic_bindings")
