import json
import sys
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from fakes import FakeAgentDb, FakeResult, today_schedule, wednesday_course  # noqa: E402

import app.channels.wecom as wecom  # noqa: E402
from app.main import app  # noqa: E402
from app.services.binding import create_binding_code, unbind_provider_identity  # noqa: E402
from app.settings import validate_settings  # noqa: E402

FakeWeComDb = FakeAgentDb

TOKEN = "callback-token"
SECRET_KEY = b"0123456789abcdef0123456789abcdef"
AES_KEY_43 = b64encode(SECRET_KEY).decode().rstrip("=")
SENDER = "zhangsan"
AIBOT_ID = "aibXV61bPoT2aXsK_test"
RESPONSE_URL = "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=RESPONSE_CODE"
ENV = {"WECOM_CALLBACK_TOKEN": TOKEN, "WECOM_ENCODING_AES_KEY": AES_KEY_43, "WECOM_AIBOT_ID": AIBOT_ID}


def message_payload(content="绑定 ABC123", msg_id="CAIQ16HM==", msg_type="text", chat_type="single",
                    response_url=RESPONSE_URL, aibot_id=AIBOT_ID, userid=SENDER):
    payload = {"msgid": msg_id, "aibotid": aibot_id, "chattype": chat_type,
               "from": {"userid": userid}, "msgtype": msg_type}
    if response_url:
        payload["response_url"] = response_url
    if msg_type == "text":
        payload["text"] = {"content": content}
    return payload


def encrypted_envelope(payload, timestamp="1757700000", nonce="nonce1", signature=None):
    encrypt = wecom.encrypt_message(json.dumps(payload, ensure_ascii=False), SECRET_KEY)
    sig = signature or wecom.message_signature(TOKEN, timestamp, nonce, encrypt)
    body = b'{"encrypt":"' + encrypt.encode() + b'"}'
    return body, {"msg_signature": sig, "timestamp": timestamp, "nonce": nonce}


@pytest.fixture
def channel(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    # 渠道测试只验证企业微信收发；LLM 主路径由 Agent 单元测试独立 mock 覆盖。
    for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL",
                 "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(wecom, "_seen_messages", {})
    sent = []

    def fake_post(url, **kwargs):
        class FakeResponse:
            def raise_for_status(self): pass

            def json(self):
                sent.append({"url": url, **kwargs.get("json", {})})
                return {"errcode": 0}
        return FakeResponse()

    monkeypatch.setattr(wecom.httpx, "post", fake_post)
    return TestClient(app), sent


def test_encrypt_decrypt_roundtrip():
    plain = '{"msgtype":"text","text":{"content":"中文内容"}}'
    cipher = wecom.encrypt_message(plain, SECRET_KEY)
    assert wecom.decrypt_message(cipher, SECRET_KEY) == plain


def test_decrypt_rejects_mismatched_receiveid():
    cipher = wecom.encrypt_message("hello", SECRET_KEY, receive_id="other-corp")
    with pytest.raises(wecom.WeComCryptoError):
        wecom.decrypt_message(cipher, SECRET_KEY, corp_id="my-corp")
    # 未配置 corp_id 时不校验 receiveid（官方文档：自建机器人 receiveid 为空串）
    assert wecom.decrypt_message(cipher, SECRET_KEY) == "hello"


def test_url_verification(channel):
    client, _ = channel
    echo = "echo-88001"
    encrypt = wecom.encrypt_message(echo, SECRET_KEY)
    params = {"msg_signature": wecom.message_signature(TOKEN, "1", "n", encrypt),
              "timestamp": "1", "nonce": "n", "echostr": encrypt}
    ok = client.get("/api/integrations/wecom/callback", params=params)
    assert ok.status_code == 200 and ok.text == echo
    params["msg_signature"] = "0" * 40
    assert client.get("/api/integrations/wecom/callback", params=params).status_code == 403


def test_callback_rejects_bad_signature(channel):
    client, sent = channel
    body, params = encrypted_envelope(message_payload(), signature="0" * 40)
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 400 and sent == []


def test_callback_rejects_malformed_envelope(channel):
    client, sent = channel
    response = client.post("/api/integrations/wecom/callback",
                           params={"msg_signature": "x", "timestamp": "1", "nonce": "n"},
                           content=b"<xml><Encrypt>legacy</Encrypt></xml>")
    assert response.status_code == 400 and sent == []


def test_callback_binds_and_replies(channel, monkeypatch):
    client, sent = channel
    db = FakeWeComDb(binding_row={"id": 1, "user_id": 7, "consumed_at": None,
                                  "expires_at": datetime.now(UTC) + timedelta(seconds=300),
                                  "attempt_count": 0})
    monkeypatch.setattr(wecom, "connect", lambda: db)
    body, params = encrypted_envelope(message_payload(content="绑定 ABC123"))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200 and response.content == b""
    assert len(sent) == 1 and sent[0]["url"] == RESPONSE_URL
    assert sent[0]["msgtype"] == "markdown" and "绑定成功" in sent[0]["markdown"]["content"]
    assert db.inserted_identities and db.inserted_identities[0] == (7, "wecom", SENDER)
    assert db.consumed_codes and db.consumed_codes[0] == (1,)


def test_callback_query_for_bound_user(channel, monkeypatch):
    client, sent = channel
    db = FakeWeComDb(identity_user_id=7, schedules=[today_schedule()], courses=[wednesday_course()])
    monkeypatch.setattr(wecom, "connect", lambda: db)
    body, params = encrypted_envelope(message_payload(content="这周有什么课"))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200
    assert len(sent) == 1 and "高数" in sent[0]["markdown"]["content"]


def test_callback_guidance_for_unbound(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb())
    body, params = encrypted_envelope(message_payload(content="今天下午有什么课"))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200
    assert sent and "绑定" in sent[0]["markdown"]["content"]


def test_callback_ignores_group_chat(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb())
    body, params = encrypted_envelope(message_payload(content="今天有什么课", chat_type="group"))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200 and sent == []


def test_callback_ignores_unknown_bot(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb())
    body, params = encrypted_envelope(message_payload(aibot_id="other-bot"))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200 and sent == []


def test_callback_non_text_without_response_url_ignored(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb())
    body, params = encrypted_envelope(message_payload(msg_type="image", response_url=""))
    response = client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert response.status_code == 200 and sent == []


def test_duplicate_message_processed_once(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb())
    body, params = encrypted_envelope(message_payload(content="今天下午有什么课", msg_id="DUP-MSG-1"))
    for _ in range(2):
        response = client.post("/api/integrations/wecom/callback", params=params, content=body)
        assert response.status_code == 200
    assert len(sent) == 1


def test_unbind_command(channel, monkeypatch):
    client, sent = channel
    monkeypatch.setattr(wecom, "connect", lambda: FakeWeComDb(delete_rowcount=1))
    body, params = encrypted_envelope(message_payload(content="解绑"))
    client.post("/api/integrations/wecom/callback", params=params, content=body)
    assert sent and "已解绑" in sent[0]["markdown"]["content"]


def test_unbind_provider_identity_rowcount():
    assert unbind_provider_identity(FakeWeComDb(delete_rowcount=1), "wecom", SENDER) == 1


def test_create_binding_code_uses_provider():
    class FakeCreateDb:
        def __init__(self): self.inserts = []

        def execute(self, sql, params=None):
            if sql.startswith("UPDATE identity_binding_codes"):
                return FakeResult([])
            if sql.startswith("INSERT INTO identity_binding_codes"):
                self.inserts.append(params)
                return FakeResult([{"id": 1}])
            raise AssertionError(sql)

    db = FakeCreateDb()
    code, _ = create_binding_code(db, 7, "wecom", 300)
    assert len(code) == 6
    assert db.inserts[0][1] == 7 and db.inserts[0][2] == "wecom"


def test_partial_wecom_config_fails_startup(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("WECHAT_DEV_OPENID", raising=False)
    monkeypatch.setenv("WECHAT_APP_ID", "wx-test")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    monkeypatch.setenv("WECOM_CALLBACK_TOKEN", TOKEN)
    with pytest.raises(RuntimeError, match="企业微信"):
        validate_settings()


def test_unconfigured_channel_returns_404(monkeypatch, channel):
    client, _ = channel
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    assert client.get("/api/integrations/wecom/callback", params={"msg_signature": "x", "timestamp": "1",
                                                                  "nonce": "n", "echostr": "e"}).status_code == 404
    assert client.post("/api/integrations/wecom/callback", params={"msg_signature": "x", "timestamp": "1",
                                                                   "nonce": "n"}, content=b"{}").status_code == 404
