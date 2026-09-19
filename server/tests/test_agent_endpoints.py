"""Agent HTTP 端点测试：debug 接口的生产关闭与开发可用。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from fakes import FakeAgentDb, today_schedule, wednesday_course  # noqa: E402

import app.routers.agent as main_module  # noqa: E402
from app.auth import get_current_user as current_user  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    app.dependency_overrides[current_user] = lambda: {"id": 7, "openid": "tester"}
    yield TestClient(app)
    app.dependency_overrides.pop(current_user, None)


def test_debug_endpoint_disabled_in_production(client):
    response = client.post("/api/agent/debug/message", json={"message": "这周有什么课"})
    assert response.status_code == 404


def test_debug_endpoint_answers_in_development(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    db = FakeAgentDb(identity_user_id=7, schedules=[today_schedule()], courses=[wednesday_course()])
    monkeypatch.setattr(main_module, "connect", lambda: db)
    response = client.post("/api/agent/debug/message", headers={"Authorization": "Bearer anything"},
                           json={"message": "这周有什么课"})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "QUERY_WEEK" and "高数" in body["answer"]
    assert set(db.schedule_query_user_ids) == {7}


def test_start_weixin_login_returns_rendered_qrcode(client, monkeypatch):
    class FakeILink:
        def get_login_qrcode(self):
            return {"qrcode": "opaque-token", "qrcode_img_content": "https://weixin.qq.com/connect/test"}

        def close(self):
            pass

    monkeypatch.setattr(main_module, "credential_key", lambda: b"k" * 32)
    monkeypatch.setattr(main_module, "reserve_start", lambda _user_id: None)
    monkeypatch.setattr(main_module, "ILinkClient", FakeILink)
    monkeypatch.setattr(main_module, "create_session",
                        lambda user_id, qrcode, image_url: {"id": "session-1", "user_id": user_id})
    response = client.post("/api/integrations/weixin/login")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["qrcode_path"] == "/api/integrations/weixin/login/session-1/qrcode"
    assert "opaque-token" not in response.text


def test_weixin_qrcode_is_same_origin_png(client, monkeypatch):
    monkeypatch.setattr(main_module, "load_session_by_id",
                        lambda session_id: {"id": session_id, "image_url": "https://weixin.qq.com/connect/test"})
    response = client.get("/api/integrations/weixin/login/session-1/qrcode")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"\x89PNG")


def test_poll_weixin_login_auto_binds_current_user(client, monkeypatch):
    class FakeILink:
        def poll_qrcode(self, qrcode, verify_code, redirect_host):
            assert (qrcode, verify_code, redirect_host) == ("qr", "123", "")
            return {"status": "confirmed", "ilink_bot_id": "bot-1", "bot_token": "secret",
                    "baseurl": "https://ilinkai.weixin.qq.com", "ilink_user_id": "wx-user-1"}

        def close(self):
            pass

    class FakeDb:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    db, saved, deleted = FakeDb(), [], []
    monkeypatch.setattr(main_module, "load_session",
                        lambda session_id, user_id: {"id": session_id, "user_id": user_id,
                                                     "qrcode": "qr", "redirect_host": ""})
    monkeypatch.setattr(main_module, "ILinkClient", FakeILink)
    monkeypatch.setattr(main_module, "connect", lambda: db)
    monkeypatch.setattr(main_module, "save_account",
                        lambda database, credentials, owner: saved.append((credentials, owner)))
    monkeypatch.setattr(main_module, "delete_session", deleted.append)
    response = client.post("/api/integrations/weixin/login/session-1/poll", json={"verify_code": "123"})
    assert response.status_code == 200 and response.json() == {"status": "confirmed", "connected": True}
    assert saved[0][0].account_id == "bot-1" and saved[0][1] == 7
    assert any("INSERT INTO user_identities" in sql for sql, _ in db.calls)
    assert deleted == ["session-1"]


def test_binding_status_lists_both_channels(client, monkeypatch):
    from datetime import datetime
    now = datetime(2026, 9, 14, 12, 0)
    db = FakeAgentDb(identity_rows=[{"provider": "weixin_ilink", "created_at": now, "last_seen_at": now}])
    monkeypatch.setattr(main_module, "connect", lambda: db)
    response = client.get("/api/agent-bindings", headers={"Authorization": "Bearer anything"})
    body = response.json()
    assert [item["provider"] for item in body["channels"]] == ["weixin_ilink", "wecom"]
    assert body["channels"][0]["bound"] is True and body["channels"][1]["bound"] is False
    assert body["bound"] is True and body["provider"] == "weixin_ilink"


def test_binding_code_honors_provider_and_rejects_unknown(client, monkeypatch):
    db = FakeAgentDb()
    monkeypatch.setattr(main_module, "connect", lambda: db)
    headers = {"Authorization": "Bearer anything"}
    response = client.post("/api/agent-bindings/code", headers=headers, json={"provider": "wecom"})
    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "wecom" and len(body["code"]) == 6
    assert db.generated_codes and db.generated_codes[0][2] == "wecom"

    assert client.post("/api/agent-bindings/code", headers=headers, json={"provider": "telegram"}).status_code == 404
    assert client.delete("/api/agent-bindings/telegram", headers=headers).status_code == 404
    assert client.delete("/api/agent-bindings/wecom", headers=headers).status_code == 204
