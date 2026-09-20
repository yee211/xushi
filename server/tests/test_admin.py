import time
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.routers import admin


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row else []


class Results:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class MockAdminDb:
    def __init__(self):
        self.admins = {}
        self.llm_configs = {}
        self.audit_logs = []
        self._next_admin_id = 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        sql_lower = sql.lower()
        if "select id from admins where username=" in sql_lower:
            username = params[0]
            for a in self.admins.values():
                if a["username"] == username:
                    return Result({"id": a["id"]})
            return Result(None)

        if "select role from admins where username=" in sql_lower:
            username = params[0]
            for a in self.admins.values():
                if a["username"] == username:
                    return Result({"role": a["role"]})
            return Result(None)

        if "select * from admins where username=" in sql_lower:
            username = params[0]
            for a in self.admins.values():
                if a["username"] == username:
                    return Result(a)
            return Result(None)

        if "select * from admins where id=" in sql_lower:
            aid = params[0]
            return Result(self.admins.get(aid))

        if "select id, username, role, created_by, created_at from admins" in sql_lower:
            return Results(list(self.admins.values()))

        if "insert into admins" in sql_lower:
            username, pwd_hash, role, created_by = params
            for a in self.admins.values():
                if a["username"].lower() == username.lower():
                    raise Exception("duplicate key value violates unique constraint")
            aid = self._next_admin_id
            self._next_admin_id += 1
            record = {
                "id": aid,
                "username": username,
                "password_hash": pwd_hash,
                "role": role,
                "created_by": created_by,
                "created_at": datetime.now(UTC),
            }
            self.admins[aid] = record
            return Result(record)

        if "delete from admins where id=" in sql_lower:
            aid = params[0]
            self.admins.pop(aid, None)
            return Result(None)

        if "insert into admin_audit_logs" in sql_lower:
            self.audit_logs.append(params)
            return Result(None)

        if "select * from llm_configs where scope=" in sql_lower:
            scope = params[0]
            return Result(self.llm_configs.get(scope))

        if "insert into llm_configs" in sql_lower:
            scope, base_url, api_key_enc, model, timeout, max_tokens, thinking = params
            self.llm_configs[scope] = {
                "scope": scope,
                "base_url": base_url,
                "api_key_encrypted": api_key_enc,
                "model": model,
                "timeout_seconds": timeout,
                "max_tokens": max_tokens,
                "enable_thinking": thinking,
            }
            return Result(None)

        if "delete from llm_configs where scope=" in sql_lower:
            scope = params[0]
            self.llm_configs.pop(scope, None)
            return Result(None)

        if "from users" in sql_lower:
            if sql_lower.strip().startswith("select count(*)"):
                return Result({"total": 1, "count": 1})
            if "where id=" in sql_lower or "where id =" in sql_lower or "where id=%" in sql_lower:
                uid = params[0]
                if uid == 101:
                    return Result({
                        "id": 101,
                        "email": "alice@example.com",
                        "username": "Alice",
                        "nickname": "Alice",
                        "openid": "wx_alice_openid",
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                        "last_login_at": datetime.now(UTC),
                    })
                elif uid == 102:
                    return Result({
                        "id": 102,
                        "email": "bob@example.com",
                        "username": "Bob",
                        "nickname": "Bob",
                        "openid": None,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                        "last_login_at": datetime.now(UTC),
                    })
                return Result(None)
            return Results([{
                "id": 101,
                "email": "alice@example.com",
                "username": "Alice",
                "nickname": "Alice",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "schedule_count": 2,
                "providers": ["wechat"],
            }])

        if "from user_identities" in sql_lower:
            return Results([{"provider": "wechat", "provider_user_id": "wx_alice_openid", "created_at": datetime.now(UTC)}])

        if "from channel_agent_bindings" in sql_lower:
            return Results([{"channel": "weixin", "bot_account_id": "bot1", "custom_nickname": "助手", "is_active": True, "created_at": datetime.now(UTC)}])

        if "from channel_accounts" in sql_lower:
            return Results([{"account_id": "bot1", "provider": "weixin", "owner_user_id": 101, "status": "online", "error_message": None, "updated_at": datetime.now(UTC)}])

        if "from schedules" in sql_lower:
            if "where id=" in sql_lower:
                sched_id = params[0]
                user_id = params[1]
                if sched_id == 201 and user_id == 101:
                    return Result({"id": 201, "user_id": 101, "name": "大三上", "semester": "2025秋", "start_date": "2025-09-01", "total_weeks": 16, "is_active": True})
                return Result(None)
            return Results([{"id": 201, "name": "大三上", "semester": "2025秋", "start_date": "2025-09-01", "total_weeks": 16, "is_active": True, "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)}])

        if "from courses" in sql_lower:
            return Results([{
                "id": 301,
                "name": "高数",
                "teacher": "张教授",
                "room": "101",
                "weekday": 1,
                "start_section": 1,
                "end_section": 2,
                "weeks": [1, 2, 3],
                "color": "#3b82f6",
            }])

        if "from sessions where user_id=" in sql_lower:
            return Results([{"token_hash": "hash_alice_session"}])

        return Result(None)


def configure(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "operator")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "x" * 40)


@pytest.fixture(autouse=True)
def mock_admin_environment(monkeypatch):
    configure(monkeypatch)
    db = MockAdminDb()
    monkeypatch.setattr(admin, "connect", lambda: db)
    monkeypatch.setattr("app.services.llm_config.connect", lambda: db)
    return db


def test_admin_token_round_trip(monkeypatch):
    configure(monkeypatch)
    token = admin.issue_token("operator")
    assert admin.current_admin(f"Bearer {token}") == "operator"


def test_admin_rejects_tampered_and_expired_tokens(monkeypatch):
    configure(monkeypatch)
    token = admin.issue_token("operator")
    with pytest.raises(HTTPException) as tampered:
        tampered_token = token[:-1] + ("1" if token.endswith("0") else "0")
        admin.current_admin(f"Bearer {tampered_token}")
    assert tampered.value.status_code == 401

    payload = f"operator:{int(time.time()) - 1}:nonce"
    expired = f"{payload}:{admin._sign(payload, 'x' * 40)}"
    with pytest.raises(HTTPException) as old:
        admin.current_admin(f"Bearer {expired}")
    assert old.value.status_code == 401


def test_admin_requires_complete_configuration(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    with pytest.raises(HTTPException) as missing:
        admin.issue_token("admin")
    assert missing.value.status_code == 503


def test_llm_configs_get_and_update(monkeypatch):
    configure(monkeypatch)
    db = MockAdminDb()
    monkeypatch.setattr(admin, "connect", lambda: db)
    monkeypatch.setattr("app.services.llm_config.connect", lambda: db)
    monkeypatch.setenv("LLM_CONFIG_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    configs = admin.llm_configs(_="operator")
    assert len(configs) == 4
    scopes = {item["scope"] for item in configs}
    assert scopes == {"schedule_import", "adjustment_vision", "agent", "polish"}

    # 更新配置
    payload = admin.LlmConfigIn(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-test-secret-123456",
        timeout_seconds=30.0,
        max_tokens=1500,
        enable_thinking=True,
    )
    saved = admin.update_llm_config("schedule_import", payload, admin="operator")
    assert saved["scope"] == "schedule_import"
    assert saved["model"] == "gpt-4o-mini"
    assert saved["api_key_configured"] is True
    assert saved["api_key_hint"] == "••••3456"
    assert saved["source"] == "database"

    # 验证 get_llm_config 内部能解密出 api_key
    from app.services.llm_config import get_llm_config
    decrypted = get_llm_config("schedule_import")
    assert decrypted["api_key"] == "sk-test-secret-123456"
    assert decrypted["model"] == "gpt-4o-mini"
    assert decrypted["enable_thinking"] is True

    # 校验非法 URL
    invalid_payload = admin.LlmConfigIn(
        base_url="ftp://invalid.com",
        model="gpt-4o-mini",
        timeout_seconds=10.0,
        max_tokens=500,
    )
    with pytest.raises(HTTPException) as exc_info:
        admin.update_llm_config("schedule_import", invalid_payload, admin="operator")
    assert exc_info.value.status_code == 400

    # 重置配置
    reset_res = admin.reset_config("schedule_import", admin="operator")
    assert reset_res["scope"] == "schedule_import"
    assert reset_res["source"] == "environment"


def test_llm_test_connection_endpoint(monkeypatch):
    configure(monkeypatch)

    # 非法 scope
    with pytest.raises(HTTPException) as invalid_scope:
        admin.test_config("unknown_scope", admin.LlmTestIn(), _="operator")
    assert invalid_scope.value.status_code == 404

    # 非法 base_url
    with pytest.raises(HTTPException) as invalid_url:
        admin.test_config("schedule_import", admin.LlmTestIn(base_url="ftp://test"), _="operator")
    assert invalid_url.value.status_code == 400

    # Mock 连接测试
    class MockResponse:
        def __init__(self, status_code=200):
            self.status_code = status_code

        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

        @property
        def text(self):
            return "OK"

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            return MockResponse(200)

    monkeypatch.setattr("app.services.llm_config.httpx.Client", MockClient)
    res = admin.test_config(
        "schedule_import",
        admin.LlmTestIn(base_url="https://api.test.com/v1", api_key="sk-test", model="test-model"),
        _="operator",
    )
    assert res["ok"] is True
    assert res["model"] == "test-model"


def test_admin_user_creation_and_login(monkeypatch):
    configure(monkeypatch)
    db = MockAdminDb()
    monkeypatch.setattr(admin, "connect", lambda: db)

    class DummyRequest:
        class Client:
            host = "127.0.0.1"
        client = Client()

    # 1. 创建新管理员
    create_payload = admin.AdminCreateIn(
        username="sub_admin_tester",
        password="complex_password_123",
        role="admin"
    )
    created = admin.create_admin(create_payload, admin="operator")
    admin_id = created["id"]
    assert created["username"] == "sub_admin_tester"
    assert created["role"] == "admin"
    assert created["created_by"] == "operator"

    # 2. 列出管理员
    admins_list = admin.list_admins(_="operator")
    users = {x["username"] for x in admins_list}
    assert "operator" in users and "sub_admin_tester" in users

    # 3. 错误密码登录失败
    with pytest.raises(HTTPException) as wrong_pwd:
        admin.admin_login(admin.AdminLoginIn(username="sub_admin_tester", password="wrong_password"), DummyRequest())
    assert wrong_pwd.value.status_code == 401

    # 4. 正确密码登录成功并取得 token
    login_res = admin.admin_login(admin.AdminLoginIn(username="sub_admin_tester", password="complex_password_123"), DummyRequest())
    token = login_res["token"]
    assert login_res["username"] == "sub_admin_tester"

    # 5. Token 鉴权成功
    assert admin.current_admin(f"Bearer {token}") == "sub_admin_tester"

    # 6. 重复用户名拦截
    with pytest.raises(HTTPException) as dup:
        admin.create_admin(create_payload, admin="operator")
    assert dup.value.status_code == 400

    # 7. 禁止删除自己
    with pytest.raises(HTTPException) as self_del:
        admin.delete_admin(admin_id, admin="sub_admin_tester")
    assert self_del.value.status_code == 400

    # 8. 操作员删除该子管理员
    del_res = admin.delete_admin(admin_id, admin="operator")
    assert del_res["ok"] is True
    assert del_res["deleted_username"] == "sub_admin_tester"

    # 9. 已删除账号的 Token 失效
    with pytest.raises(HTTPException) as revoked:
        admin.current_admin(f"Bearer {token}")
    assert revoked.value.status_code == 401


def test_require_superadmin_blocks_regular_admin(monkeypatch):
    configure(monkeypatch)
    db = MockAdminDb()
    monkeypatch.setattr(admin, "connect", lambda: db)
    normal_admin = {
        "id": 2,
        "username": "junior_admin",
        "password_hash": admin.hash_password("pw123456"),
        "role": "admin",
        "created_by": "operator",
        "created_at": datetime.now(UTC),
    }
    db.admins[2] = normal_admin

    token = admin.issue_token("junior_admin")
    assert admin.current_admin(f"Bearer {token}") == "junior_admin"
    assert admin.admin_role("junior_admin") == "admin"

    with pytest.raises(HTTPException) as exc:
        admin.require_superadmin("junior_admin")
    assert exc.value.status_code == 403
    assert "超级管理员" in exc.value.detail


def test_admin_web_routes():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "序时 · 管理后台" in resp.text

    resp_slash = client.get("/admin/")
    assert resp_slash.status_code == 200
    assert "序时 · 管理后台" in resp_slash.text

    resp_css = client.get("/admin/static/admin.css")
    assert resp_css.status_code == 200

    resp_js = client.get("/admin/static/admin.js")
    assert resp_js.status_code == 200


def test_favicon_returns_204():
    from app.main import favicon
    res = favicon()
    assert res.status_code == 204


def test_admin_list_users():
    res = admin.list_users(query="alice", limit=20, offset=0, _="operator")
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["id"] == 101
    assert res["items"][0]["nickname"] == "Alice"
    assert res["items"][0]["schedule_count"] == 2
    assert "wechat" in res["items"][0]["providers"]


def test_admin_get_user_detail():
    res = admin.get_user_detail(user_id=101, _="operator")
    assert res["user"]["id"] == 101
    assert res["user"]["username"] == "Alice"
    assert len(res["identities"]) == 1
    assert res["identities"][0]["provider"] == "wechat"
    assert len(res["schedules"]) == 1
    assert res["schedules"][0]["id"] == 201
    assert len(res["bots"]) == 1
    assert res["bots"][0]["account_id"] == "bot1"


def test_admin_get_user_detail_not_found():
    with pytest.raises(HTTPException) as exc:
        admin.get_user_detail(user_id=999, _="operator")
    assert exc.value.status_code == 404


def test_admin_get_schedule_courses():
    res = admin.get_schedule_courses(user_id=101, schedule_id=201, _="operator")
    assert res["schedule"]["id"] == 201
    assert res["schedule"]["name"] == "大三上"
    assert len(res["courses"]) == 1
    assert res["courses"][0]["name"] == "高数"
    assert res["courses"][0]["teacher"] == "张教授"


def test_admin_get_schedule_courses_not_found():
    with pytest.raises(HTTPException) as exc:
        admin.get_schedule_courses(user_id=101, schedule_id=999, _="operator")
    assert exc.value.status_code == 404


def test_admin_unbind_wechat(monkeypatch):
    unlinked = []
    monkeypatch.setattr("app.services.account_link.unlink_wechat", lambda db, uid: unlinked.append(uid))
    res = admin.admin_unbind_wechat(user_id=101, admin="operator")
    assert res["ok"] is True
    assert unlinked == [101]


def test_admin_unbind_wechat_no_openid():
    with pytest.raises(HTTPException) as exc:
        admin.admin_unbind_wechat(user_id=102, admin="operator")
    assert exc.value.status_code == 400
    assert "未绑定微信" in exc.value.detail


def test_admin_unbind_wechat_not_found():
    with pytest.raises(HTTPException) as exc:
        admin.admin_unbind_wechat(user_id=999, admin="operator")
    assert exc.value.status_code == 404


def test_admin_system_status(monkeypatch):
    class DummyRedis:
        def info(self):
            return {"used_memory_human": "2.5M", "connected_clients": 3, "redis_version": "7.0.5", "uptime_in_days": 12}

        def dbsize(self):
            return 42

    monkeypatch.setattr("app.redis.get_redis", lambda: DummyRedis())
    res = admin.system_status(_="operator")
    assert res["redis"]["connected"] is True
    assert res["redis"]["used_memory_human"] == "2.5M"
    assert res["redis"]["total_keys"] == 42
    assert len(res["bots"]) == 1
    assert res["bots"][0]["account_id"] == "bot1"


def test_admin_clear_ratelimit(monkeypatch):
    class DummyRedis:
        def scan_iter(self, match=None, count=None):
            return ["xushi:ratelimit:api:127.0.0.1", "xushi:ratelimit:auth:127.0.0.1"]

        def delete(self, *keys):
            return len(keys)

    monkeypatch.setattr("app.redis.get_redis", lambda: DummyRedis())
    res = admin.clear_ratelimit(admin.ClearRateLimitIn(key="127.0.0.1"), admin="operator")
    assert res["ok"] is True
    assert res["deleted_count"] == 2


def test_admin_clear_user_sessions(monkeypatch):
    invalidated = []
    monkeypatch.setattr("app.auth.deps.invalidate_session_cache", lambda token_digest=None: invalidated.append(token_digest))
    res = admin.clear_user_sessions(admin.ClearSessionIn(user_id=101), admin="operator")
    assert res["ok"] is True
    assert res["cleared_count"] == 1
    assert invalidated == ["hash_alice_session"]




