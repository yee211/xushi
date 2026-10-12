"""Regressions for the remaining review findings."""
import json
import time
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from psycopg.pq import TransactionStatus

from app.agent.http_client import post_llm
from app.channels import wecom
from app.excel import _decode
from app.services import academic_runtime, weather


@pytest.mark.parametrize("enabled", [False, True])
def test_deepseek_adapter_covers_fallback_requests(monkeypatch, enabled):
    captured = {}
    def post(url, **kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr("app.agent.http_client.httpx.post", post)
    post_llm("https://api.deepseek.com/chat/completions", json={"enable_thinking": enabled})
    assert captured["json"] == {"thinking": {"type": "enabled" if enabled else "disabled"}}


@pytest.mark.parametrize("timestamp", ["invalid", "1", str(int(time.time()) + 10000)])
def test_signed_stale_callback_is_rejected(timestamp):
    key = b"x" * 32
    encrypted = wecom.encrypt_message(json.dumps({"msgtype":"text"}), key)
    settings = {"token":"test", "aes_key":key}
    body = json.dumps({"encrypt":encrypted}).encode()
    signature = wecom.message_signature("test", timestamp, "nonce", encrypted)
    with pytest.raises(wecom.WeComCryptoError):
        wecom.handle_callback(settings, body, signature, timestamp, "nonce", BackgroundTasks())


def test_messages_without_msgid_do_not_collide_in_the_same_second(monkeypatch):
    monkeypatch.setattr(wecom, "_seen_messages", {})
    monkeypatch.setattr(wecom, "get_redis", lambda: None)
    settings = {"token":"test", "aes_key":b"x" * 32}
    timestamp = str(int(time.time()))
    tasks = BackgroundTasks()
    for text in ("今天有课吗", "明天有课吗"):
        payload = {"msgtype":"text", "from":{"userid":"sender"}, "text":{"content":text}, "response_url":"https://example.test/reply"}
        encrypted = wecom.encrypt_message(json.dumps(payload), settings["aes_key"])
        body = json.dumps({"encrypt":encrypted}).encode()
        signature = wecom.message_signature("test", timestamp, "nonce", encrypted)
        wecom.handle_callback(settings, body, signature, timestamp, "nonce", tasks)
    assert len(tasks.tasks) == 2
    # Replaying the same message is still deduplicated.
    wecom.handle_callback(settings, body, signature, timestamp, "nonce", tasks)
    assert len(tasks.tasks) == 2


def test_committed_transaction_is_not_reported_as_timeout():
    class DB:
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        def execute(self, *args):
            pass
        def cancel(self):
            raise AssertionError("Already committed transaction must not be cancelled")
    db = DB()
    with academic_runtime.execution(0.01):
        with academic_runtime.transaction(db):
            db.info.transaction_status = TransactionStatus.IDLE
            time.sleep(0.03)


@pytest.mark.parametrize("encoding, text", [("big5", "課程 星期 教師 學期"), ("gb18030", "课程 星期 教师 学期")])
def test_chinese_encoding_ambiguity_is_resolved(tmp_path, encoding, text):
    path = tmp_path / "schedule.xls"
    path.write_bytes(text.encode(encoding))
    assert _decode(path) == text


def test_weather_uses_configured_timezone_and_separates_cache(monkeypatch):
    captured = []
    monkeypatch.setenv("WEATHER_LATITUDE", "40")
    monkeypatch.setenv("WEATHER_LONGITUDE", "-74")
    monkeypatch.setattr(weather, "_CACHE", {})
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"hourly":{"time":["2026-10-12T08:00"], "precipitation_probability":[0], "weather_code":[0]}}
    def get(url, **kwargs):
        captured.append(kwargs["params"]["timezone"])
        return Response()
    monkeypatch.setattr(weather.httpx, "get", get)
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    weather.fetch_hourly(date(2026, 10, 12))
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")
    weather.fetch_hourly(date(2026, 10, 12))
    assert captured == ["America/New_York", "Asia/Shanghai"]


def test_release_invalid_version_code_has_clean_error(monkeypatch, capsys):
    from scripts import release
    monkeypatch.setattr(release.sys, "argv", ["release.py", "1.2.3", "invalid"])
    with pytest.raises(SystemExit) as error:
        release.main()
    assert error.value.code == 2
    assert "发布参数错误" in capsys.readouterr().err


def test_unknown_ilink_error_is_retryable(monkeypatch):
    from app.channels.weixin.client import ILinkError
    from app.services import daily_push
    statuses = []
    monkeypatch.setattr(daily_push, "build_morning_brief", lambda *a: "brief")
    monkeypatch.setattr(daily_push, "_record_push_result", lambda db, user, day, status, err: statuses.append(status))
    class Client:
        def send_text(self, *args, **kwargs):
            raise ILinkError("upstream temporarily busy", code="5001")
    assert not daily_push.send_morning_push_to_user(None, Client(), 1, "sender", "context", date(2026, 10, 12))
    assert statuses == ["failed"]


def test_transport_child_logger_redacts_at_handler():
    import io
    import logging

    from app.observability import RedactHttpSecrets
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RedactHttpSecrets())
    parent = logging.getLogger("review-transport")
    child = logging.getLogger("review-transport.child")
    old = parent.handlers, parent.propagate, parent.level
    try:
        parent.handlers = [handler]
        parent.propagate = False
        parent.setLevel(logging.INFO)
        child.info("request https://example.test/api?token=secret-value")
        assert "secret-value" not in output.getvalue()
        assert "REDACTED" in output.getvalue()
    finally:
        parent.handlers, parent.propagate, parent.level = old


def test_redaction_preserves_uvicorn_access_formatter_arguments():
    import logging

    from uvicorn.logging import AccessFormatter

    from app.observability import RedactHttpSecrets
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:1234", "GET", "/api/live", "1.1", 200), None)
    assert RedactHttpSecrets().filter(record)
    formatted = AccessFormatter('%(request_line)s %(status_code)s').format(record)
    assert "GET /api/live HTTP/1.1" in formatted
    assert "200" in formatted
