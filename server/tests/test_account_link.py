"""账号互通：绑定码生成/消费与小程序账号并入邮箱账号的合并逻辑。"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from fakes import FakeResult  # noqa: E402

from app.services import account_link  # noqa: E402
from app.services.account_link import AccountLinkError  # noqa: E402


@pytest.fixture
def client_module():
    """带会话用户覆盖的 TestClient；模拟小程序端 Bearer 会话令牌。"""
    from app.auth import get_current_user as current_user
    from app.main import app

    user = shell_user()
    app.dependency_overrides[current_user] = lambda: dict(user)
    yield TestClient(app)
    app.dependency_overrides.pop(current_user, None)


class FakeLinkDb:
    """按 SQL 前缀路由的离线假库，记录全部语句供断言。"""

    def __init__(self, wx_user=None, target_user=None, binding_row=None,
                 wx_identities=(), wx_schedules=(), target_schedules=()):
        self.wx_user, self.target_user = wx_user, target_user
        self.binding_row = binding_row
        self.wx_identities = list(wx_identities)
        self.wx_schedules, self.target_schedules = list(wx_schedules), list(target_schedules)
        self.calls = []

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        if sql.startswith("SELECT openid FROM users"):
            return FakeResult([{"openid": self.wx_user["openid"]}] if self.wx_user else [])
        if sql.startswith("SELECT id, openid, email, username FROM users"):
            return FakeResult([dict(self.target_user)] if self.target_user else [])
        if sql.startswith("SELECT * FROM identity_binding_codes"):
            return FakeResult([self.binding_row] if self.binding_row else [])
        if sql.startswith("SELECT id, provider FROM user_identities"):
            return FakeResult(list(self.wx_identities))
        if sql.startswith("SELECT id, start_date, end_date FROM schedules"):
            return FakeResult(list(self.wx_schedules))
        if sql.startswith("SELECT start_date, end_date FROM schedules"):
            return FakeResult(list(self.target_schedules))
        if sql.startswith("UPDATE identity_binding_codes"):
            return FakeResult([])
        if sql.startswith("INSERT INTO identity_binding_codes"):
            return FakeResult([{"id": 1}])
        if sql.startswith("UPDATE sessions SET user_id"):
            return FakeResult([], rowcount=1)
        if sql.startswith("DELETE FROM user_identities"):
            return FakeResult([], rowcount=1)
        if sql.startswith("UPDATE user_identities"):
            return FakeResult([], rowcount=1)
        if sql.startswith("UPDATE channel_accounts"):
            return FakeResult([], rowcount=0)
        if sql.startswith("UPDATE feedbacks"):
            return FakeResult([], rowcount=0)
        if sql.startswith("UPDATE schedules SET user_id=%s WHERE user_id"):
            return FakeResult([], rowcount=len(self.wx_schedules))
        if sql.startswith("UPDATE schedules SET user_id=%s WHERE id"):
            return FakeResult([], rowcount=1)
        if sql.startswith("DELETE FROM schedules"):
            return FakeResult([], rowcount=1)
        if sql.startswith("DELETE FROM users"):
            self.wx_user = None
            return FakeResult([], rowcount=1)
        if sql.startswith("UPDATE users SET openid"):
            return FakeResult([], rowcount=1)
        if sql.startswith("INSERT INTO users"):
            return FakeResult([{"id": 99}])
        if sql.startswith("SELECT id FROM schedules WHERE user_id"):
            return FakeResult([])
        if sql.startswith("SELECT id, name, term, start_date, end_date, background FROM schedules WHERE user_id"):
            return FakeResult([{"id": 1, "name": "默认课表", "term": "2026秋", "start_date": "2026-09-01", "end_date": "2027-01-20", "background": ""}])
        if sql.startswith("INSERT INTO schedules"):
            return FakeResult([{"id": 101}])
        if sql.startswith("SELECT name, teacher, room, weekday, start_section, end_section, weeks, color FROM courses"):
            return FakeResult([{"name": "高等数学", "teacher": "张老师", "room": "101", "weekday": 1, "start_section": 1, "end_section": 2, "weeks": [1, 2], "color": "#1890ff"}])
        if sql.startswith("INSERT INTO courses"):
            return FakeResult([], rowcount=1)
        if sql.startswith("DELETE FROM sessions"):
            return FakeResult([], rowcount=1)
        raise AssertionError(sql)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def binding_row(user_id=5, expired=False, consumed=False):
    return {"id": 1, "user_id": user_id, "expires_at": datetime.now(UTC) + (timedelta(days=-1) if expired else timedelta(minutes=4)),
            "consumed_at": datetime.now(UTC) if consumed else None}


def shell_user(user_id=9, openid="ox123"):
    return {"id": user_id, "openid": openid, "email": "", "username": ""}


def call(sql_part, db):
    return [params for sql, params in db.calls if sql_part in sql]


# ---------- 绑定码生成 ----------

def test_create_link_code_for_unbound_account():
    db = FakeLinkDb(wx_user={"openid": None})
    code, expires = account_link.create_link_code(db, 5, ttl_seconds=300)
    assert len(code) == 6 and expires > datetime.now(UTC)
    assert call("INSERT INTO identity_binding_codes", db)


def test_create_link_code_rejects_already_bound():
    db = FakeLinkDb(wx_user={"openid": "ox123"})
    with pytest.raises(AccountLinkError) as error:
        account_link.create_link_code(db, 5)
    assert error.value.code == "ALREADY_BOUND"
    assert not call("INSERT INTO identity_binding_codes", db)


# ---------- 绑定：正常合并 ----------

def test_link_merges_shell_account_into_email_account():
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "a@b.c", "username": "tom"},
                    binding_row=binding_row(user_id=5))
    summary = account_link.link_wechat_account(db, "ABCD23", shell_user())
    assert summary["email"] == "a@b.c" and summary["username"] == "tom"
    assert call("DELETE FROM users", db) == [(9,)]
    assert call("UPDATE users SET openid", db) == [("ox123", 5)]
    assert call("UPDATE sessions SET user_id", db) == [(5, 9)]
    assert call("UPDATE identity_binding_codes SET consumed_at=CURRENT_TIMESTAMP WHERE id", db)
    assert not call("DELETE FROM schedules", db)


def test_link_moves_identities_and_replaces_same_provider():
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "", "username": ""},
                    binding_row=binding_row(user_id=5),
                    wx_identities=[{"id": 3, "provider": "weixin_ilink"}])
    summary = account_link.link_wechat_account(db, "ABCD23", shell_user())
    assert summary["agent_bindings_moved"] == 1
    assert call("DELETE FROM user_identities", db) == [(5, "weixin_ilink")]
    assert call("UPDATE user_identities", db) == [(5, 3)]


def test_link_without_target_schedules_moves_all():
    schedules = [{"id": 11, "start_date": None, "end_date": None}]
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "", "username": ""},
                    binding_row=binding_row(user_id=5), wx_schedules=schedules)
    summary = account_link.link_wechat_account(db, "ABCD23", shell_user())
    assert summary["schedules_moved"] == 1 and summary["schedules_discarded"] == 0
    assert call("UPDATE schedules SET user_id=%s WHERE id", db) == [(5, 11)]


def test_link_dedups_mutually_overlapping_wx_schedules():
    """小程序侧两张互相重叠的课表（即使目标账号无课表）也只保留一张。"""
    schedules = [{"id": 11, "start_date": "2026-09-07", "end_date": "2027-01-20"},
                 {"id": 12, "start_date": "2026-10-01", "end_date": "2027-01-31"}]
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "", "username": ""},
                    binding_row=binding_row(user_id=5), wx_schedules=schedules)
    summary = account_link.link_wechat_account(db, "ABCD23", shell_user())
    assert summary["schedules_moved"] == 1 and summary["schedules_discarded"] == 1
    assert call("DELETE FROM schedules", db) == [(12,)]
    assert call("UPDATE schedules SET user_id=%s WHERE id", db) == [(5, 11)]


def test_link_discards_overlapping_schedules_and_keeps_disjoint():
    wx = [{"id": 11, "start_date": "2026-09-07", "end_date": "2027-01-20"},
          {"id": 12, "start_date": "2026-02-20", "end_date": "2026-06-30"}]
    target = [{"start_date": "2026-09-10", "end_date": None}]
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "", "username": ""},
                    binding_row=binding_row(user_id=5), wx_schedules=wx, target_schedules=target)
    summary = account_link.link_wechat_account(db, "ABCD23", shell_user())
    assert summary["schedules_moved"] == 1 and summary["schedules_discarded"] == 1
    assert call("DELETE FROM schedules", db) == [(11,)]
    assert call("UPDATE schedules SET user_id=%s WHERE id", db) == [(5, 12)]


# ---------- 绑定：失败路径 ----------

@pytest.mark.parametrize("code,row,wx,target,expected", [
    ("", binding_row(), shell_user(), {"id": 5, "openid": None}, "INVALID_CODE"),
    ("ABC", binding_row(), shell_user(), {"id": 5, "openid": None}, "INVALID_CODE"),
    ("WRONG1", None, shell_user(), {"id": 5, "openid": None}, "INVALID_CODE"),
    ("EXPIRED", binding_row(expired=True), shell_user(), {"id": 5, "openid": None}, "INVALID_CODE"),
    ("USEDONE", binding_row(consumed=True), shell_user(), {"id": 5, "openid": None}, "INVALID_CODE"),
    ("GHOSTY", binding_row(user_id=404), shell_user(), None, "INVALID_CODE"),
    ("ABC123", binding_row(user_id=9), shell_user(), {"id": 9, "openid": None}, "SELF_BIND"),
    ("ABC123", binding_row(user_id=5), shell_user(), {"id": 5, "openid": "other"}, "TARGET_BOUND"),
])
def test_link_rejects_invalid_scenarios(code, row, wx, target, expected):
    db = FakeLinkDb(wx_user=wx, target_user=target, binding_row=row)
    with pytest.raises(AccountLinkError) as error:
        account_link.link_wechat_account(db, code, wx)
    assert error.value.code == expected
    assert not call("DELETE FROM users", db)


def test_link_requires_wechat_identity():
    db = FakeLinkDb()
    with pytest.raises(AccountLinkError) as error:
        account_link.link_wechat_account(db, "ABC123", {"id": 9, "openid": None})
    assert error.value.code == "NO_OPENID"


def test_link_rejects_already_linked_wechat_session():
    linked = {"id": 9, "openid": "ox123", "email": "x@y.z", "username": ""}
    db = FakeLinkDb(wx_user=linked, target_user={"id": 5, "openid": None}, binding_row=binding_row(user_id=5))
    with pytest.raises(AccountLinkError) as error:
        account_link.link_wechat_account(db, "ABC123", linked)
    assert error.value.code == "WX_HAS_EMAIL"


# ---------- 解绑 ----------

def test_unlink_clears_openid_and_revokes_sessions():
    db = FakeLinkDb(wx_user={"openid": "ox123"})
    res = account_link.unlink_wechat(db, 9)
    assert res["wx_user_id"] == 99
    assert call("UPDATE users SET openid=NULL", db) == [(9,)]
    assert call("INSERT INTO users(openid) VALUES(%s)", db) == [("ox123",)]
    assert call("DELETE FROM sessions", db) == [(9,)]


def test_unlink_migrates_identities_and_preserves_schedule():
    db = FakeLinkDb(wx_user={"openid": "ox123"},
                    wx_identities=[{"id": 3, "provider": "weixin_ilink"}])
    res = account_link.unlink_wechat(db, 9)
    assert res["wx_user_id"] == 99
    assert res["agent_bindings_moved"] == 1
    assert call("DELETE FROM user_identities WHERE user_id=%s AND provider=%s", db) == [(99, "weixin_ilink")]
    assert call("UPDATE user_identities SET user_id=%s WHERE id=%s", db) == [(99, 3)]
    assert call("UPDATE channel_accounts SET owner_user_id=%s WHERE owner_user_id=%s AND provider='weixin_ilink'", db) == [(99, 9)]
    assert call("INSERT INTO schedules(user_id, name, term, start_date, end_date, background)", db)
    assert call("INSERT INTO courses(schedule_id, name, teacher, room, weekday, start_section, end_section, weeks, color)", db)


def test_unlink_requires_bound_wechat():
    db = FakeLinkDb(wx_user={"openid": None})
    with pytest.raises(AccountLinkError) as error:
        account_link.unlink_wechat(db, 9)
    assert error.value.code == "NOT_BOUND"
    assert not call("DELETE FROM sessions", db)


# ---------- HTTP 端点 ----------

def test_link_endpoint_merges_and_returns_summary(client_module, monkeypatch):
    from app.routers import account_link as router_module
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": None, "email": "a@b.c", "username": "tom"},
                    binding_row=binding_row(user_id=5))
    monkeypatch.setattr(router_module, "connect", lambda: db)
    response = client_module.post("/api/account/link", headers={"Authorization": "Bearer session-token"},
                                  json={"code": "ABCD23"})
    assert response.status_code == 200
    body = response.json()
    assert body["linked"] is True and body["email"] == "a@b.c"


def test_link_endpoint_conflict_when_target_bound(client_module, monkeypatch):
    from app.routers import account_link as router_module
    db = FakeLinkDb(wx_user=shell_user(), target_user={"id": 5, "openid": "taken", "email": "", "username": ""},
                    binding_row=binding_row(user_id=5))
    monkeypatch.setattr(router_module, "connect", lambda: db)
    response = client_module.post("/api/account/link", headers={"Authorization": "Bearer session-token"},
                                  json={"code": "ABCD23"})
    assert response.status_code == 409 and "其他微信" in response.json()["detail"]


def test_unlink_endpoint_requires_bound_account(client_module, monkeypatch):
    from app.routers import account_link as router_module
    db = FakeLinkDb(wx_user={"openid": None})
    monkeypatch.setattr(router_module, "connect", lambda: db)
    response = client_module.delete("/api/account/link", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 400


def test_unlink_endpoint_success(client_module, monkeypatch):
    from app.routers import account_link as router_module
    db = FakeLinkDb(wx_user={"openid": "ox123"})
    monkeypatch.setattr(router_module, "connect", lambda: db)
    response = client_module.delete("/api/account/link", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 204


def test_status_endpoint_reports_binding_state(client_module, monkeypatch):
    from app.routers import account_link as router_module

    class StatusDb(FakeLinkDb):
        def execute(self, sql, params=None):
            sql = " ".join(sql.split())
            if sql.startswith("SELECT openid, email, username FROM users"):
                return FakeResult([{"openid": "ox123", "email": "a@b.c", "username": "tom"}])
            return super().execute(sql, params)

    db = StatusDb()
    monkeypatch.setattr(router_module, "connect", lambda: db)
    response = client_module.get("/api/account/link", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 200
    assert response.json() == {"openid_bound": True, "email": "a@b.c", "username": "tom"}
