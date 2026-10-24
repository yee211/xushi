"""user_cleanup 单测：过期裸 openid 用户的删除条件、保留期开关与会话缓存失效。"""
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.services import user_cleanup  # noqa: E402


class Result:
    def __init__(self, rows):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class FakeDb:
    def __init__(self, digests=(), doomed=()):
        self.calls = []
        self._digests = digests
        self._doomed = doomed

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        low = sql.lower()
        if "select s.token_hash" in low:
            return Result(list(self._digests))
        if "delete from users" in low:
            return Result(list(self._doomed))
        return Result([])


@pytest.fixture
def capture_invalidate(monkeypatch):
    calls = []
    monkeypatch.setattr("app.auth.deps.invalidate_session_cache",
                        lambda token_digest=None, token=None: calls.append(token_digest))
    return calls


def test_cleanup_skipped_when_retention_disabled(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(user_cleanup, "connect", lambda: db)
    monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "0")
    assert user_cleanup.cleanup() == 0
    assert db.calls == []


def test_cleanup_deletes_inert_users_and_invalidates_sessions(monkeypatch, capture_invalidate):
    db = FakeDb(digests=[{"token_hash": "abc"}], doomed=[{"id": 9}, {"id": 10}])
    monkeypatch.setattr(user_cleanup, "connect", lambda: db)
    monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "30")
    assert user_cleanup.cleanup() == 2
    assert len(db.calls) == 2
    digest_sql, delete_sql = db.calls[0][0], db.calls[1][0]
    for sql in (digest_sql, delete_sql):
        low = sql.lower()
        assert "u.openid is not null" in low
        assert "u.username is null" in low
        # 绑定口径与 admin.BOUND_USER_FILTER 同源（NOT 整段共享定义）
        assert "not (" in low
        assert "u.email is not null and u.email <> ''" in low
        assert "user_identities" in low and "academic_bindings" in low
        # 有课表或反馈的用户不允许删
        assert "from schedules" in low and "from feedbacks" in low
        # 会话仍未过期的活跃用户不允许删（缓存 token 可直接复用）
        assert "sessions se" in low and "se.expires_at > current_timestamp" in low
        assert "u.last_login_at < current_timestamp" in low
        assert "coalesce" not in low
    assert db.calls[0][1] == (30,) and db.calls[1][1] == (30,)
    assert capture_invalidate == ["abc"]


def test_cleanup_keeps_zero_deletion_silent(monkeypatch, capture_invalidate):
    db = FakeDb(digests=[{"token_hash": "abc"}], doomed=[])
    monkeypatch.setattr(user_cleanup, "connect", lambda: db)
    monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "30")
    assert user_cleanup.cleanup() == 0
    assert capture_invalidate == []


def test_retention_days_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "not-a-number")
    assert user_cleanup.retention_days() == 30
    monkeypatch.delenv("UNBOUND_USER_RETENTION_DAYS")
    assert user_cleanup.retention_days() == 30
    monkeypatch.setenv("UNBOUND_USER_RETENTION_DAYS", "7")
    assert user_cleanup.retention_days() == 7
