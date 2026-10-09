"""Complete local school student directory."""
from alembic import op

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS academic_directory_students (
        id TEXT PRIMARY KEY,grade TEXT NOT NULL,payload JSONB NOT NULL,search_text TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_academic_directory_grade ON academic_directory_students(grade)",
    """CREATE TABLE IF NOT EXISTS academic_directory_control (
        id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL DEFAULT 'idle',
        grades JSONB NOT NULL DEFAULT '[]',synced_at TIMESTAMPTZ,
        student_count INTEGER NOT NULL DEFAULT 0,classes_done INTEGER NOT NULL DEFAULT 0,
        classes_total INTEGER NOT NULL DEFAULT 0,error TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    "INSERT INTO academic_directory_control(id) VALUES(1) ON CONFLICT DO NOTHING",
)

revision = '0015_academic_directory'
down_revision = '0014_schedule_backups'
branch_labels = None
depends_on = None


def upgrade():
    for sql in SCHEMA:
        op.execute(sql)


def downgrade():
    op.execute('DROP TABLE IF EXISTS academic_directory_students')
    op.execute('DROP TABLE IF EXISTS academic_directory_control')
