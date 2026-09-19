"""统一数据库 Schema（幂等初始化 + 两套旧库就地升级）。

users 表是两侧旧版的超集：网页端用户有 email/username/password_hash，
小程序端用户有 openid，两者均可为空以兼容另一侧。其余业务表以
小程序版（后演进的一侧）为基准，feedbacks 为网页版 feedback 的超集。

旧库升级路径（init_db 直接在启动时执行，无需 alembic 版本对齐）：
- 网页母版库：users 补 openid/last_login_at，feedback 数据迁入 feedbacks；
- 小程序版库：users 补 email/username/password_hash。
"""
import json
import os

# 注意：直接从叶子模块导入，避免 db <-> auth 包级循环导入
from ..auth.passwords import hash_password
from .pool import connect


def _table_exists(db, name: str) -> bool:
    return db.execute("SELECT to_regclass(%s) AS oid", (name,)).fetchone()["oid"] is not None


def _ensure_default_user(db):
    """确保存在默认账号，用于接管升级前无主的课表数据。登录凭证为邮箱。"""
    username = os.getenv("DEFAULT_USERNAME", "demo")
    email = os.getenv("DEFAULT_EMAIL", "demo@example.com").strip().lower()
    password = os.getenv("DEFAULT_PASSWORD", "demo1234")
    row = db.execute("SELECT id,email FROM users WHERE username=%s", (username,)).fetchone()
    if row:
        if row["email"] != email:
            db.execute("""UPDATE users SET email=%s WHERE id=%s
                AND NOT EXISTS (SELECT 1 FROM users u WHERE u.email=%s)""", (email, row["id"], email))
        return row["id"]
    return db.execute(
        "INSERT INTO users(email,username,password_hash) VALUES(%s,%s,%s) RETURNING id",
        (email, username, hash_password(password)),
    ).fetchone()["id"]


def init_db():
    with connect() as db:
        # ---------- 用户与会话 ----------
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            email VARCHAR(254) UNIQUE,
            username VARCHAR(40) UNIQUE,
            password_hash VARCHAR(200),
            openid VARCHAR(128) UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        # 旧网页母版库：users 原本 email NOT NULL，本补列语句在其上无副作用
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS openid VARCHAR(128)")
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
        # 旧小程序版库：users 原本 openid NOT NULL，补上邮箱体系三列
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254)")
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40)")
        db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(200)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users(email)")
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash CHAR(64) PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id)")

        # ---------- 课表 / 课程 / 调课 ----------
        db.execute("""CREATE TABLE IF NOT EXISTS schedules (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(80) NOT NULL,
            term VARCHAR(80) NOT NULL DEFAULT '',
            start_date DATE,
            end_date DATE,
            background TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS end_date DATE")
        db.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS variant_type VARCHAR(16) NOT NULL DEFAULT 'draft'")
        db.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS source_schedule_id BIGINT REFERENCES schedules(id) ON DELETE CASCADE")
        db.execute("""CREATE TABLE IF NOT EXISTS courses (
            id BIGSERIAL PRIMARY KEY,
            schedule_id BIGINT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            name VARCHAR(80) NOT NULL, teacher VARCHAR(40) NOT NULL DEFAULT '',
            room VARCHAR(40) NOT NULL DEFAULT '', weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
            start_section SMALLINT NOT NULL CHECK (start_section BETWEEN 1 AND 12),
            end_section SMALLINT NOT NULL CHECK (end_section BETWEEN 1 AND 12),
            weeks JSONB NOT NULL DEFAULT '[]'::jsonb, color VARCHAR(16) NOT NULL DEFAULT '#5B8DEF',
            CHECK (end_section >= start_section))""")
        db.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS source_course_id BIGINT REFERENCES courses(id) ON DELETE SET NULL")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_schedules_adjusted_source
            ON schedules(source_schedule_id) WHERE variant_type='adjusted'""")
        db.execute("""CREATE TABLE IF NOT EXISTS course_adjustments (
            id BIGSERIAL PRIMARY KEY,
            course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            week SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 30),
            weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
            start_section SMALLINT NOT NULL CHECK (start_section BETWEEN 1 AND 12),
            end_section SMALLINT NOT NULL CHECK (end_section BETWEEN 1 AND 12),
            room VARCHAR(40) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (course_id, week),
            CHECK (end_section >= start_section))""")
        db.execute("""CREATE TABLE IF NOT EXISTS course_change_logs (
            id BIGSERIAL PRIMARY KEY,
            schedule_id BIGINT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            course_id BIGINT REFERENCES courses(id) ON DELETE SET NULL,
            action_type VARCHAR(32) NOT NULL,
            title VARCHAR(120) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            details JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("ALTER TABLE course_change_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(80)")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS change_logs_schedule_request_uidx
            ON course_change_logs(schedule_id, request_id) WHERE request_id IS NOT NULL""")
        # 索引：外键与高频查询
        db.execute("CREATE INDEX IF NOT EXISTS idx_courses_schedule_id ON courses(schedule_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_courses_source_course_id ON courses(source_course_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_course_adjustments_course_id ON course_adjustments(course_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_course_change_logs_schedule_id ON course_change_logs(schedule_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_course_change_logs_created_at ON course_change_logs(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_schedules_user_id ON schedules(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_schedules_user_id_term ON schedules(user_id, term)")

        # ---------- 渠道身份 / Agent ----------
        db.execute("""CREATE TABLE IF NOT EXISTS user_identities (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            provider_user_id VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider,provider_user_id), UNIQUE(user_id,provider))""")
        db.execute("ALTER TABLE user_identities ADD COLUMN IF NOT EXISTS account_id VARCHAR(255)")
        db.execute("CREATE INDEX IF NOT EXISTS user_identities_account_idx ON user_identities(provider,account_id)")
        db.execute("""CREATE TABLE IF NOT EXISTS identity_binding_codes (
            id BIGSERIAL PRIMARY KEY,
            code_hash CHAR(64) NOT NULL UNIQUE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            attempt_count SMALLINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE INDEX IF NOT EXISTS binding_codes_user_idx ON identity_binding_codes(user_id,provider)")
        db.execute("""CREATE TABLE IF NOT EXISTS channel_accounts (
            id BIGSERIAL PRIMARY KEY,
            provider VARCHAR(32) NOT NULL,
            account_id VARCHAR(255) NOT NULL,
            bot_token_encrypted TEXT NOT NULL,
            api_base_url TEXT NOT NULL,
            admin_user_id VARCHAR(255) NOT NULL DEFAULT '',
            owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            update_cursor TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider,account_id))""")
        db.execute("ALTER TABLE channel_accounts ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL")
        db.execute("""CREATE TABLE IF NOT EXISTS channel_messages (
            provider VARCHAR(32) NOT NULL,
            account_id VARCHAR(255) NOT NULL,
            message_id VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMPTZ,
            PRIMARY KEY(provider,account_id,message_id))""")
        db.execute("CREATE INDEX IF NOT EXISTS channel_messages_processed_idx ON channel_messages(processed_at)")

        # ---------- 反馈（网页版 feedback 的超集） ----------
        db.execute("""CREATE TABLE IF NOT EXISTS feedbacks (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            schedule_id BIGINT REFERENCES schedules(id) ON DELETE SET NULL,
            category VARCHAR(32) NOT NULL,
            description TEXT NOT NULL,
            contact VARCHAR(120) NOT NULL DEFAULT '',
            client_info JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            admin_note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE INDEX IF NOT EXISTS feedbacks_status_created_idx ON feedbacks(status, created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS feedbacks_user_created_idx ON feedbacks(user_id, created_at DESC)")
        # 旧网页母版库的单表 feedback：结构允许时把历史数据并入 feedbacks（仅一次）
        if _table_exists(db, "feedback") and not db.execute("SELECT 1 FROM feedbacks LIMIT 1").fetchone():
            feedback_columns = {row["column_name"] for row in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='feedback'").fetchall()}
            if {"user_id", "category", "description"} <= feedback_columns:
                db.execute("""INSERT INTO feedbacks(user_id,category,description,contact,client_info,status,created_at)
                    SELECT user_id,category,description,contact,client_info,status,created_at FROM feedback""")

        # ---------- 管理后台 ----------
        db.execute("""CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'admin',
            created_by VARCHAR(64) NOT NULL DEFAULT 'system',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id BIGSERIAL PRIMARY KEY,
            admin_name VARCHAR(64) NOT NULL,
            action VARCHAR(64) NOT NULL,
            target_type VARCHAR(64) NOT NULL,
            target_id VARCHAR(120) NOT NULL DEFAULT '',
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE INDEX IF NOT EXISTS admin_audit_created_idx ON admin_audit_logs(created_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS api_request_logs (
            id BIGSERIAL PRIMARY KEY,
            method VARCHAR(10) NOT NULL,
            path VARCHAR(255) NOT NULL,
            status SMALLINT NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("CREATE INDEX IF NOT EXISTS api_request_logs_created_idx ON api_request_logs(created_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS api_request_logs_path_created_idx ON api_request_logs(path, created_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS llm_configs (
            scope VARCHAR(32) PRIMARY KEY,
            base_url VARCHAR(500) NOT NULL DEFAULT '',
            api_key_encrypted TEXT NOT NULL DEFAULT '',
            model VARCHAR(120) NOT NULL DEFAULT '',
            timeout_seconds NUMERIC(5,2) NOT NULL DEFAULT 30,
            max_tokens INTEGER NOT NULL DEFAULT 1000,
            enable_thinking BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

        # ---------- 启动期清理 ----------
        db.execute("DELETE FROM sessions WHERE expires_at <= CURRENT_TIMESTAMP")
        db.execute("DELETE FROM identity_binding_codes WHERE expires_at <= CURRENT_TIMESTAMP")
        db.execute("DELETE FROM channel_messages WHERE processed_at < CURRENT_TIMESTAMP - INTERVAL '30 days'")
        db.execute("DELETE FROM api_request_logs WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'")

        _seed_demo(db)


def _seed_demo(db):
    """空库种子：默认账号 + 一份示例课表（对齐网页母版行为）。"""
    if db.execute("SELECT 1 FROM schedules LIMIT 1").fetchone():
        return
    default_user_id = _ensure_default_user(db)
    db.execute("UPDATE schedules SET user_id=%s WHERE user_id IS NULL", (default_user_id,))
    sid = db.execute(
        "INSERT INTO schedules(user_id,name,term,start_date) VALUES(%s,%s,%s,%s) RETURNING id",
        (default_user_id, "我的课表", "2026-2027-1学期", "2026-09-07"),
    ).fetchone()["id"]
    weeks = json.dumps(list(range(1, 9)))
    demo = [
        (sid, "数据采集与预处理", "李老师", "南313", 2, 1, 2, weeks, "#EF4770"),
        (sid, "计算机组成原理", "李老师", "南407", 3, 1, 2, weeks, "#F1763F"),
        (sid, "开源软件开发", "张老师", "南508", 4, 1, 2, weeks, "#8D68D7"),
        (sid, "应用程序设计", "付老师", "南405", 3, 3, 4, weeks, "#63B75A"),
        (sid, "计算机网络", "龙老师", "南312", 4, 3, 4, weeks, "#3D9DDB"),
    ]
    with db.cursor() as cursor:
        cursor.executemany("""INSERT INTO courses
            (schedule_id,name,teacher,room,weekday,start_section,end_section,weeks,color)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", demo)
