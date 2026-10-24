"""Real PostgreSQL regressions; opt in only against a disposable test database."""
import os
from contextlib import contextmanager

import pytest

from app.db import connect
from app.services import user_activity, user_cleanup


@pytest.fixture
def database(monkeypatch):
    if os.getenv("TEST_ACTIVITY_DB") != "1":
        pytest.skip("disposable PostgreSQL not configured")
    with connect() as db:
        db.execute("""CREATE TEMP TABLE users (
            id BIGINT PRIMARY KEY, openid TEXT, username TEXT, email TEXT,
            last_login_at TIMESTAMPTZ, last_active_at TIMESTAMPTZ) ON COMMIT DROP""")
        for name, column in (("schedules", "user_id"), ("feedbacks", "user_id"),
                             ("academic_others", "user_id"), ("schedule_backups", "user_id"),
                             ("channel_accounts", "owner_user_id"), ("user_identities", "user_id"),
                             ("academic_bindings", "user_id")):
            db.execute(f"CREATE TEMP TABLE {name} ({column} BIGINT REFERENCES users(id) ON DELETE CASCADE) ON COMMIT DROP")
        db.execute("""CREATE TEMP TABLE sessions (user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT, expires_at TIMESTAMPTZ) ON COMMIT DROP""")
        db.execute("""INSERT INTO users(id,openid,last_login_at)
            VALUES (1,'synthetic',CURRENT_TIMESTAMP - INTERVAL '60 days')""")

        @contextmanager
        def shared():
            yield db

        monkeypatch.setattr(user_cleanup, "connect", shared)
        monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "30")
        yield db


@pytest.mark.parametrize("table,column", [
    ("academic_others", "user_id"), ("schedule_backups", "user_id"),
    ("channel_accounts", "owner_user_id"), ("schedules", "user_id"),
    ("feedbacks", "user_id"), ("academic_bindings", "user_id"),
    ("user_identities", "user_id"),
])
def test_cleanup_preserves_users_with_saved_data(database, table, column):
    database.execute(f"INSERT INTO {table}({column}) VALUES (1)")
    assert user_cleanup.cleanup() == 0
    assert database.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 1
    assert database.execute("SELECT id FROM users").fetchone()["id"] == 1


def test_cleanup_still_removes_truly_empty_expired_user(database):
    assert user_cleanup.cleanup() == 1
    assert database.execute("SELECT id FROM users").fetchone() is None


def test_cleanup_preserves_live_session(database):
    database.execute("INSERT INTO sessions VALUES (1,'synthetic',CURRENT_TIMESTAMP + INTERVAL '1 day')")
    assert user_cleanup.cleanup() == 0


def test_activity_records_usage_without_login_and_throttles_writes(database):
    before = database.execute("SELECT last_login_at FROM users WHERE id=1").fetchone()["last_login_at"]
    user_activity.touch(database, 1)
    first = database.execute("SELECT last_active_at FROM users WHERE id=1").fetchone()
    assert first["last_active_at"] is not None
    # A second update inside the same minute must not rewrite the row.
    row = database.execute("SELECT ctid::text AS version FROM users WHERE id=1").fetchone()
    user_activity.touch(database, 1)
    assert database.execute("SELECT ctid::text AS version FROM users WHERE id=1").fetchone() == row
    assert database.execute("SELECT last_login_at FROM users WHERE id=1").fetchone()["last_login_at"] == before
    database.execute("UPDATE users SET last_active_at=CURRENT_TIMESTAMP - INTERVAL '2 minutes' WHERE id=1")
    user_activity.touch(database, 1)
    assert database.execute("SELECT last_active_at FROM users WHERE id=1").fetchone()["last_active_at"] == first["last_active_at"]


@pytest.mark.parametrize("user_id,status,expected", [(7,200,True), (7,401,False), (None,200,False)])
def test_metrics_writer_only_records_authenticated_success(monkeypatch, user_id, status, expected):
    import queue
    import threading
    from unittest.mock import MagicMock

    from app.services import request_metrics

    pending = queue.Queue()
    stopped = threading.Event()
    touched = []
    db = MagicMock()
    db.__enter__.return_value = db

    def execute(statement, *args):
        if statement.startswith("DELETE"):
            stopped.set()

    db.execute.side_effect = execute
    monkeypatch.setattr(request_metrics, "connect", lambda: db)
    monkeypatch.setattr(request_metrics, "_pending", pending)
    monkeypatch.setattr(request_metrics, "_stop", stopped)
    monkeypatch.setattr(request_metrics, "touch", lambda conn, uid: touched.append(uid))
    request_metrics.enqueue("GET", "/api/me", status, 1, user_id)
    request_metrics._worker()
    assert touched == ([7] if expected else [])


def test_worker_records_activity_without_context_token(monkeypatch):
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from app.channels.weixin import worker
    from app.channels.weixin.protocol import InboundText

    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchone.return_value = {"user_id": 7}
    monkeypatch.setattr(worker, "connect", lambda: db)
    monkeypatch.setattr(worker, "claim_message", lambda *args: True)
    monkeypatch.setattr(worker, "load_reply", lambda *args: "stored reply")
    monkeypatch.setattr(worker, "complete_message", lambda *args: None)
    touched = []
    monkeypatch.setattr(worker.user_activity, "touch", lambda conn, uid: touched.append(uid))
    message = InboundText("bot", "sender", "message", "hello", "", datetime.now(UTC))
    assert worker.process_message(MagicMock(), message)
    assert touched == [7]
