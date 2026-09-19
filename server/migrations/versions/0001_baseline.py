"""基线：与 app.db.init_db 等价的幂等建表。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-12
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    """CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        openid VARCHAR(128) NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash CHAR(64) PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS schedules (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(80) NOT NULL,
        term VARCHAR(80) NOT NULL DEFAULT '',
        start_date DATE,
        end_date DATE,
        background TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS courses (
        id BIGSERIAL PRIMARY KEY,
        schedule_id BIGINT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
        name VARCHAR(80) NOT NULL,
        teacher VARCHAR(40) NOT NULL DEFAULT '',
        room VARCHAR(40) NOT NULL DEFAULT '',
        weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
        start_section SMALLINT NOT NULL CHECK (start_section BETWEEN 1 AND 12),
        end_section SMALLINT NOT NULL CHECK (end_section BETWEEN 1 AND 12),
        weeks JSONB NOT NULL DEFAULT '[]'::jsonb,
        color VARCHAR(16) NOT NULL DEFAULT '#5B8DEF',
        CHECK (end_section >= start_section))""",
    """CREATE TABLE IF NOT EXISTS course_adjustments (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        week SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 30),
        weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
        start_section SMALLINT NOT NULL CHECK (start_section BETWEEN 1 AND 12),
        end_section SMALLINT NOT NULL CHECK (end_section BETWEEN 1 AND 12),
        room VARCHAR(40) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (course_id, week),
        CHECK (end_section >= start_section))""",
    """CREATE TABLE IF NOT EXISTS course_change_logs (
        id BIGSERIAL PRIMARY KEY,
        schedule_id BIGINT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
        course_id BIGINT REFERENCES courses(id) ON DELETE SET NULL,
        action_type VARCHAR(32) NOT NULL,
        title VARCHAR(120) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        details JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS schedules_user_id_idx ON schedules(user_id)",
    "CREATE INDEX IF NOT EXISTS schedules_user_term_idx ON schedules(user_id, term)",
    "CREATE INDEX IF NOT EXISTS courses_schedule_id_idx ON courses(schedule_id)",
    "CREATE INDEX IF NOT EXISTS courses_source_course_id_idx ON courses(source_course_id)",
    """CREATE UNIQUE INDEX IF NOT EXISTS schedules_adjusted_source_idx
       ON schedules(source_schedule_id) WHERE variant_type='adjusted'""",
    "CREATE INDEX IF NOT EXISTS adjustments_course_id_idx ON course_adjustments(course_id)",
    "CREATE INDEX IF NOT EXISTS change_logs_schedule_id_idx ON course_change_logs(schedule_id)",
    "CREATE INDEX IF NOT EXISTS change_logs_schedule_created_idx ON course_change_logs(schedule_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id)",
)

COLUMNS = (
    "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS variant_type VARCHAR(16) NOT NULL DEFAULT 'draft'",
    "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS source_schedule_id BIGINT REFERENCES schedules(id) ON DELETE CASCADE",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS source_course_id BIGINT REFERENCES courses(id) ON DELETE SET NULL",
)


def upgrade() -> None:
    for statement in TABLES + COLUMNS + INDEXES:
        op.execute(statement)


def downgrade() -> None:
    pass  # 基线不做降级，避免误删业务数据
