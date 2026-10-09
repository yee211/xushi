"""Align upgraded schemas and bound background retries."""
from alembic import op

revision = "0016_audit_repairs"
down_revision = "0015_academic_directory"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ALTER COLUMN openid DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN email DROP NOT NULL")
    op.execute("ALTER TABLE feedbacks ALTER COLUMN category TYPE VARCHAR(32)")
    op.execute("ALTER TABLE feedbacks ALTER COLUMN description TYPE TEXT")
    op.execute("ALTER TABLE daily_push_logs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 1")

    # Rename old initializer/migration aliases, removing only identical duplicates.
    pairs = [('schedules_user_id_idx', 'idx_schedules_user_id'), ('schedules_user_term_idx', 'idx_schedules_user_id_term'), ('courses_schedule_id_idx', 'idx_courses_schedule_id'), ('courses_source_course_id_idx', 'idx_courses_source_course_id'), ('schedules_adjusted_source_idx', 'uq_schedules_adjusted_source'), ('adjustments_course_id_idx', 'idx_course_adjustments_course_id'), ('change_logs_schedule_id_idx', 'idx_course_change_logs_schedule_id')]
    for old, new in pairs:
        op.execute(f"""DO $$ BEGIN
            IF to_regclass('{old}') IS NOT NULL THEN
                IF to_regclass('{new}') IS NULL THEN
                    ALTER INDEX {old} RENAME TO {new};
                ELSIF substring(pg_get_indexdef(to_regclass('{old}')) FROM ' ON .*') =
                      substring(pg_get_indexdef(to_regclass('{new}')) FROM ' ON .*') THEN
                    DROP INDEX {old};
                END IF;
            END IF;
        END $$""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_course_change_logs_created_at ON course_change_logs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS change_logs_schedule_created_idx ON course_change_logs(schedule_id,created_at DESC)")


def downgrade():
    op.execute("ALTER TABLE daily_push_logs DROP COLUMN IF EXISTS attempts")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS attempts")
    # Narrowing populated fields or restoring NOT NULL would discard valid data.
