"""Contract tests for the OpenClaw-independent Tencent iLink adapter."""
import base64
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.channels.weixin.client import ILinkClient, ILinkError, reply_client_id  # noqa: E402
from app.channels.weixin.protocol import Credentials, extract_text_items  # noqa: E402
from app.channels.weixin.store import decrypt_token, encrypt_token  # noqa: E402


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data, self.status_code = data, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.data


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(self.responses.pop(0))

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self.responses.pop(0))

    def close(self):
        pass


class FailingGetHttp(FakeHttp):
    def get(self, url, **kwargs):
        raise httpx.ConnectError("temporary")


def credentials():
    return Credentials("bot-1", "secret-token", "https://api.example.qq.com")


def test_qrcode_request_has_no_bearer_token(monkeypatch):
    monkeypatch.setenv("WEIXIN_ILINK_CHANNEL_VERSION", "2.4.8")
    http = FakeHttp([{"qrcode": "qr", "qrcode_img_content": "image"}])
    result = ILinkClient(http=http).get_login_qrcode()
    method, url, kwargs = http.calls[0]
    assert method == "POST" and url.endswith("/ilink/bot/get_bot_qrcode?bot_type=3")
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["headers"]["AuthorizationType"] == "ilink_bot_token"
    assert kwargs["headers"]["iLink-App-ClientVersion"] == str((2 << 16) | (4 << 8) | 8)
    assert result["qrcode"] == "qr"


def test_qrcode_redirect_host_gets_https_scheme():
    http = FakeHttp([{"status": "wait"}])
    ILinkClient(http=http).poll_qrcode("qr", redirect_host="redirect.example.qq.com")
    assert http.calls[0][1].startswith("https://redirect.example.qq.com/")


def test_qrcode_network_error_is_treated_as_wait():
    assert ILinkClient(http=FailingGetHttp([])).poll_qrcode("qr") == {"status": "wait"}


def test_get_updates_sends_cursor_and_auth():
    http = FakeHttp([{"ret": 0, "msgs": [], "get_updates_buf": "next"}])
    result = ILinkClient(credentials(), http=http).get_updates("previous")
    _, _, kwargs = http.calls[0]
    assert kwargs["json"]["get_updates_buf"] == "previous"
    assert kwargs["json"]["base_info"]["bot_agent"]
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert result["get_updates_buf"] == "next"


def test_get_updates_rejects_business_error():
    client = ILinkClient(credentials(), http=FakeHttp([{"ret": -14, "errmsg": "expired"}]))
    with pytest.raises(ILinkError, match="-14"):
        client.get_updates()


def test_get_updates_handles_timeout_as_empty_cycle():
    class TimingOutPostHttp(FakeHttp):
        def post(self, url, **kwargs):
            raise httpx.ReadTimeout("read timed out")

    client = ILinkClient(credentials(), http=TimingOutPostHttp([]))
    result = client.get_updates("prev-cursor", timeout=4.0)
    assert result["msgs"] == []
    assert result["get_updates_buf"] == "prev-cursor"
    assert result["ret"] == 0


def test_send_text_preserves_context_and_stable_client_id():
    http = FakeHttp([{"ret": 0}])
    client = ILinkClient(credentials(), http=http)
    stable = reply_client_id("bot-1", "42")
    assert stable == reply_client_id("bot-1", "42")
    client.send_text("user-1", "你好", "context-1", client_id=stable, run_id="run-1")
    msg = http.calls[0][2]["json"]["msg"]
    assert msg["to_user_id"] == "user-1" and msg["context_token"] == "context-1"
    assert msg["client_id"] == stable and msg["run_id"] == "run-1"
    assert msg["item_list"][0]["text_item"]["text"] == "你好"


def test_send_text_allows_optional_context_token():
    http = FakeHttp([{"ret": 0}])
    client = ILinkClient(credentials(), http=http)
    client.send_text("u", "x", "", client_id="id")
    msg = http.calls[0][2]["json"]["msg"]
    assert msg["to_user_id"] == "u"
    assert "context_token" not in msg


def test_get_config_and_send_typing():
    http = FakeHttp([{"ret": 0, "typing_ticket": "ticket-123"}, {"ret": 0}])
    client = ILinkClient(credentials(), http=http)
    cfg = client.get_config("user-1", "ctx-token")
    assert cfg["typing_ticket"] == "ticket-123"
    assert http.calls[0][1].endswith("/ilink/bot/getconfig")
    assert http.calls[0][2]["json"]["ilink_user_id"] == "user-1"
    assert http.calls[0][2]["json"]["context_token"] == "ctx-token"

    client.send_typing("user-1", "ticket-123", status=1)
    assert http.calls[1][1].endswith("/ilink/bot/sendtyping")
    assert http.calls[1][2]["json"]["typing_ticket"] == "ticket-123"
    assert http.calls[1][2]["json"]["status"] == 1


def test_send_typing_indicator_caches_ticket_and_handles_error():
    # First call: getconfig returns ticket, sendtyping succeeds
    # Second call: uses cached ticket, doesn't call getconfig again
    http = FakeHttp([
        {"ret": 0, "typing_ticket": "ticket-abc"},
        {"ret": 0},
        {"ret": 0},
    ])
    client = ILinkClient(credentials(), http=http)
    client.send_typing_indicator("user-1", "ctx-token", status=1)
    assert len(http.calls) == 2  # 1 getconfig + 1 sendtyping

    client.send_typing_indicator("user-1", "ctx-token", status=1)
    assert len(http.calls) == 3  # 1 sendtyping only (cached)

    # Safe error handling: failing HTTP should not raise
    failing_client = ILinkClient(credentials(), http=FailingGetHttp([]))
    failing_client.send_typing_indicator("user-2", "ctx-token")  # must not raise


def test_extract_text_and_voice_transcript():
    raw = {"message_type": 1, "message_id": 42, "from_user_id": "u1", "context_token": "ctx",
           "item_list": [{"type": 1, "text_item": {"text": "今天"}},
                         {"type": 3, "voice_item": {"text": "有什么课"}}]}
    result = extract_text_items(raw, "bot-1", datetime.now(UTC))
    assert result and result.text == "今天\n有什么课" and result.message_id == "42"


def test_credential_encryption_roundtrip(monkeypatch):
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    monkeypatch.setenv("WEIXIN_ILINK_CREDENTIAL_KEY", key)
    encrypted = encrypt_token("bot-token")
    assert encrypted != "bot-token"
    assert decrypt_token(encrypted) == "bot-token"


def test_credential_key_must_be_32_bytes(monkeypatch):
    monkeypatch.setenv("WEIXIN_ILINK_CREDENTIAL_KEY", base64.urlsafe_b64encode(b"short").decode())
    with pytest.raises(RuntimeError, match="32 字节"):
        encrypt_token("bot-token")


class FakeRows:
    def __init__(self, rows): self.rows = rows

    def fetchall(self): return self.rows

    def fetchone(self): return self.rows[0] if self.rows else None


class FakeStateDb:
    def __init__(self, rows): self.rows, self.queries = rows, []

    def execute(self, sql, params=None):
        self.queries.append(sql)
        return FakeRows(self.rows)


def test_load_accounts_returns_token_fingerprint(monkeypatch):
    from app.channels.weixin import store as store_module
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    monkeypatch.setenv("WEIXIN_ILINK_CREDENTIAL_KEY", key)
    encrypted = encrypt_token("secret-token")
    db = FakeStateDb([{"account_id": "bot-1", "bot_token_encrypted": encrypted,
                       "api_base_url": "https://api.example.qq.com", "admin_user_id": "u1",
                       "update_cursor": "cur"}])
    (credentials, cursor, fingerprint), = store_module.load_accounts(db)
    assert credentials.bot_token == "secret-token" and cursor == "cur"
    monkeypatch.setenv("WEIXIN_ILINK_CREDENTIAL_KEY", key)
    rotated = FakeStateDb([{"account_id": "bot-1", "bot_token_encrypted": encrypt_token("rotated-token"),
                            "api_base_url": "https://api.example.qq.com", "admin_user_id": "u1",
                            "update_cursor": "cur"}])
    (_, _, new_fingerprint), = store_module.load_accounts(rotated)
    assert new_fingerprint != fingerprint


def test_reset_stale_processing_marks_rows_failed():
    from app.channels.weixin import store as store_module
    db = FakeStateDb([("m1",), ("m2",)])
    assert store_module.reset_stale_processing(db) == 2
    assert "status='processing'" in db.queries[0] and "status='failed'" in db.queries[0]


def test_reconcile_starts_stops_and_rotates_threads():
    import threading

    from app.channels.weixin import worker as worker_module

    def live_spawn(credentials, cursor, stop_event):
        # 契约：spawn 返回未启动的线程，由 reconcile_threads 负责启动
        return threading.Thread(target=stop_event.wait, daemon=True)

    bot = Credentials("bot-1", "t1", "https://api.example.qq.com")
    threads: dict = {}
    worker_module.reconcile_threads(threads, [(bot, "", "fp1")], spawn=live_spawn)
    assert threads["bot-1"][2] == "fp1" and threads["bot-1"][0].is_alive()

    worker_module.reconcile_threads(threads, [(bot, "", "fp2")], spawn=live_spawn)
    assert threads["bot-1"][1].is_set(), "token 轮换必须停掉旧线程"
    old_thread = threads["bot-1"][0]
    old_thread.join(timeout=2)
    worker_module.reconcile_threads(threads, [(bot, "", "fp2")], spawn=live_spawn)
    assert threads["bot-1"][2] == "fp2" and threads["bot-1"][0] is not old_thread
    assert threads["bot-1"][0].is_alive()

    worker_module.reconcile_threads(threads, [], spawn=live_spawn)
    assert threads["bot-1"][1].is_set(), "账号被移除后必须停线程"


def test_process_batch_messages_concurrent_for_different_users(monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.channels.weixin import worker as worker_module
    from app.channels.weixin.protocol import InboundText

    processed = []
    def fake_process(client, msg):
        time.sleep(0.05)
        processed.append((msg.sender_id, msg.message_id))
        return True

    monkeypatch.setattr(worker_module, "process_message", fake_process)
    msgs = [
        InboundText("bot-1", "user-1", "m1", "t1", "ctx1", datetime.now(UTC)),
        InboundText("bot-1", "user-2", "m2", "t2", "ctx2", datetime.now(UTC)),
        InboundText("bot-1", "user-3", "m3", "t3", "ctx3", datetime.now(UTC)),
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        t0 = time.monotonic()
        ok = worker_module.process_batch_messages(None, msgs, executor=executor)
        elapsed = time.monotonic() - t0

    assert ok is True
    assert len(processed) == 3
    # 3 条不同用户的消息并发执行耗时应显著小于串行耗时 (3 * 0.05s = 0.15s)
    assert elapsed < 0.12


def test_process_batch_messages_sequential_for_same_user(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.channels.weixin import worker as worker_module
    from app.channels.weixin.protocol import InboundText

    order = []
    def fake_process(client, msg):
        order.append(msg.message_id)
        return True

    monkeypatch.setattr(worker_module, "process_message", fake_process)
    msgs = [
        InboundText("bot-1", "user-1", "m1", "t1", "ctx1", datetime.now(UTC)),
        InboundText("bot-1", "user-1", "m2", "t2", "ctx2", datetime.now(UTC)),
        InboundText("bot-1", "user-1", "m3", "t3", "ctx3", datetime.now(UTC)),
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        ok = worker_module.process_batch_messages(None, msgs, executor=executor)

    assert ok is True
    assert order == ["m1", "m2", "m3"], "同一用户的消息必须严格按序处理"


def test_process_batch_messages_failure_stops_cursor(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.channels.weixin import worker as worker_module
    from app.channels.weixin.protocol import InboundText

    def failing_process(client, msg):
        return msg.message_id != "fail"

    monkeypatch.setattr(worker_module, "process_message", failing_process)
    msgs = [
        InboundText("bot-1", "user-1", "ok1", "t1", "ctx1", datetime.now(UTC)),
        InboundText("bot-1", "user-2", "fail", "t2", "ctx2", datetime.now(UTC)),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        ok = worker_module.process_batch_messages(None, msgs, executor=executor)

    assert ok is False


def test_db_pool_reads_environment_variables(monkeypatch):
    from app.db import pool as db_module

    monkeypatch.setenv("DB_POOL_MIN_SIZE", "8")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "45")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "25.0")

    db_module.close_pool()
    try:
        # Mock ConnectionPool to verify args
        created_kwargs = {}
        class FakePool:
            def __init__(self, *args, **kwargs):
                created_kwargs.update(kwargs)
            def close(self): pass

        monkeypatch.setattr(db_module, "ConnectionPool", FakePool)
        db_module.init_pool()
        assert created_kwargs.get("min_size") == 8
        assert created_kwargs.get("max_size") == 45
        assert created_kwargs.get("timeout") == 25.0
    finally:
        db_module.close_pool()


def test_poll_account_batch_success_and_failure(monkeypatch):
    import threading

    from app.channels.weixin import worker as worker_module

    saved_cursors = []
    def fake_save_cursor(db, account_id, cursor):
        saved_cursors.append((account_id, cursor))

    monkeypatch.setattr(worker_module, "save_cursor", fake_save_cursor)
    monkeypatch.setattr(worker_module, "connect", lambda: FakeContextDb())

    class FakeContextDb:
        def __enter__(self): return self
        def __exit__(self, *args): pass

    stop_event = threading.Event()
    def fake_process_success(client, msgs, executor=None):
        stop_event.set()
        return True

    monkeypatch.setattr(worker_module, "process_batch_messages", fake_process_success)
    bot = Credentials("bot-1", "t1", "https://api.example.qq.com")
    http = FakeHttp([
        {"ret": 0},  # notify start
        {
            "ret": 0,
            "msgs": [{"message_type": 1, "message_id": "1", "from_user_id": "u1", "context_token": "c1",
                      "item_list": [{"type": 1, "text_item": {"text": "hello"}}]}],
            "get_updates_buf": "cursor-after-success",
        },
        {"ret": 0},  # notify stop
    ])
    monkeypatch.setattr(worker_module, "ILinkClient", lambda creds: FakeClientWithNotify(http))

    worker_module.poll_account(bot, "initial-cursor", stop_event=stop_event)
    assert ("bot-1", "cursor-after-success") in saved_cursors

    # Case 2: Batch fails -> cursor does not advance
    saved_cursors.clear()
    stop_event_fail = threading.Event()
    def fake_process_fail(client, msgs, executor=None):
        stop_event_fail.set()
        return False

    monkeypatch.setattr(worker_module, "process_batch_messages", fake_process_fail)
    http_fail = FakeHttp([
        {"ret": 0},  # notify start
        {
            "ret": 0,
            "msgs": [{"message_type": 1, "message_id": "2", "from_user_id": "u2", "context_token": "c2",
                      "item_list": [{"type": 1, "text_item": {"text": "hello"}}]}],
            "get_updates_buf": "cursor-after-fail",
        },
        {"ret": 0},  # notify stop
    ])
    monkeypatch.setattr(worker_module, "ILinkClient", lambda creds: FakeClientWithNotify(http_fail))
    worker_module.poll_account(bot, "initial-cursor", stop_event=stop_event_fail)
    assert len(saved_cursors) == 0, "批次失败时不应推进并保存游标"


class FakeClientWithNotify:
    def __init__(self, http):
        self.http = http
    def notify(self, started):
        self.http.post("/notify", json={"started": started})
    def get_updates(self, cursor):
        return self.http.post("/getupdates", json={"cursor": cursor}).json()
    def close(self):
        pass
