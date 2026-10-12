import asyncio
import logging
import time

import httpx
import pytest

from app.observability import RedactHttpSecrets
from app.services import academic, academic_runtime


def test_transport_url_parameters_are_redacted():
    record = logging.LogRecord("httpx", logging.INFO, "", 0,
                               "HTTP Request: %s %s", ("GET", "https://tls.ccsut.cn/report?a=secret&_sn=token"), None)
    RedactHttpSecrets().filter(record)
    assert "secret" not in record.getMessage()
    assert "token" not in record.getMessage()
    assert "https://tls.ccsut.cn/report?[REDACTED]" in record.getMessage()


def test_budget_restores_context_after_timeout():
    with academic_runtime.execution(0):
        with pytest.raises(academic_runtime.SyncTimeout):
            academic_runtime.check()
    assert academic_runtime.remaining(60) == 60


def test_budget_rejects_commit_after_expiry():
    class DB:
        def execute(self, *args):
            pass

        def cancel(self):
            pass

    with academic_runtime.execution(0.02):
        with pytest.raises(academic_runtime.SyncTimeout):
            with academic_runtime.transaction(DB()):
                time.sleep(0.04)


def test_budget_cancels_waiting_database_operation():
    import threading
    cancelled = threading.Event()

    class DB:
        def execute(self, *args):
            pass

        def cancel(self):
            cancelled.set()

    with academic_runtime.execution(0.02):
        with pytest.raises(academic_runtime.SyncTimeout):
            with academic_runtime.transaction(DB()):
                assert cancelled.wait(0.5)
    assert cancelled.is_set()


def test_total_http_deadline_interrupts_slow_response_body(monkeypatch):
    monkeypatch.setattr("app.services.academic_rate_limit.acquire", lambda deadline: None)

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "  # Progress must not reset the total timeout.

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowBody()))
    with academic.CcsutClient({"Cookie": "test"}, transport=transport) as client:
        client.deadline = time.monotonic() + 0.04
        started = time.monotonic()
        with pytest.raises(academic.AcademicError) as error:
            client.request("GET", "/admin/api/getKbxx?userId=secret")
    assert error.value.code == "upstream_timeout"
    assert time.monotonic() - started < 0.5


def test_exception_trace_urls_are_redacted():
    from app.observability import RedactingFormatter
    try:
        raise RuntimeError("request failed https://tls.ccsut.cn/report?_sn=secret")
    except RuntimeError:
        import sys
        record = logging.LogRecord("app", logging.ERROR, "", 0, "failure", (), sys.exc_info())
    formatted = RedactingFormatter(logging.Formatter("%(message)s")).format(record)
    assert "secret" not in formatted
    assert "RuntimeError" in formatted
