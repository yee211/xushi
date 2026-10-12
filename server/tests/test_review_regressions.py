from datetime import date

import pytest
from openpyxl import Workbook

from app.agent import loop
from app.agent.orchestrator import _target_day
from app.excel import read_sheets
from app.parser import _parse_grid_course_block, parse_weeks


@pytest.mark.parametrize("expression, expected", [
    ("1 7-9周", [1,7,8,9]), ("1 3 5周", [1,3,5]),
    ("1 - 5 (单)周", [1,3,5]), ("1-5(单)9-15(单)周", [1,3,5,9,11,13,15]),
])
def test_spaced_week_lists(expression, expected):
    assert parse_weeks(expression) == expected

@pytest.mark.parametrize("text, expected", [
    ("下下周三", date(2026,10,28)), ("上周三", date(2026,10,7)),
    ("下星期天", date(2026,10,25)), ("本周三", date(2026,10,14)),
])
def test_relative_weekdays(text, expected):
    assert _target_day(text, date(2026,10,12)) == expected

def test_inline_course_teacher_weeks():
    result = _parse_grid_course_block("高等数学 肖裕【1-16周】 A101", 1, 1, 2)
    assert result["name"] == "高等数学"
    assert result["teacher"] == "肖裕"
    assert result["weeks"] == list(range(1,17))

def test_vertical_excel_merge(tmp_path):
    book=Workbook()
    sheet=book.active
    sheet["A1"]="课程"
    sheet.merge_cells("A1:A3")
    path=tmp_path/"merged.xlsx"
    book.save(path)
    rows=dict(read_sheets(path)[0].rows)
    assert all(rows[row][1] == "课程" for row in (1,2,3))

def test_runtime_agent_config(monkeypatch):
    from test_agent_loop import configure, make_tools, reply_message
    sent=configure(monkeypatch,[reply_message(content="你好")])
    monkeypatch.setattr(loop,"get_llm_config",lambda scope: {"timeout_seconds":7,"max_tokens":123,"enable_thinking":True})
    assert loop.run(make_tools(), "你好") is not None
    assert sent[0]["max_tokens"] == 123
    assert sent[0]["enable_thinking"] is True

def test_historical_timestamp_does_not_ground_course_time(monkeypatch):
    from test_agent_loop import configure, make_tools, reply_message
    configure(monkeypatch,[reply_message(content="今天 08:00 上课")])
    assert loop.run(make_tools(), "今天有什么课", [{"role":"user","content":"消息时间 08:00"}]) is None


def test_timeout_preserves_original_exception():
    import time

    from app.services import academic_runtime
    class DB:
        def execute(self, *args):
            pass
        def cancel(self):
            pass
    with academic_runtime.execution(0.01):
        with pytest.raises(ValueError, match="original failure"):
            with academic_runtime.transaction(DB()):
                time.sleep(0.03)
                raise ValueError("original failure")


def test_teacher_number_is_not_a_week():
    result = _parse_grid_course_block("高等数学\n肖裕2 1-16周", 1, 1, 2)
    assert result["teacher"] == "肖裕2"
    assert result["weeks"] == list(range(1, 17))


def test_metrics_queue_drops_overflow_without_blocking(monkeypatch):
    import queue

    from app.services import request_metrics
    pending = queue.Queue(maxsize=1)
    monkeypatch.setattr(request_metrics, "_pending", pending)
    request_metrics.enqueue("GET", "/health", 200, 1)
    request_metrics.enqueue("GET", "/health", 200, 1)
    assert pending.qsize() == 1


def test_metrics_worker_writes_and_cleans_old_rows(monkeypatch):
    import queue
    import threading

    from app.services import request_metrics
    pending = queue.Queue(maxsize=2)
    stopped = threading.Event()
    statements = []
    class DB:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, sql, *args):
            statements.append(sql)
            if sql.startswith("DELETE"):
                stopped.set()
    monkeypatch.setattr(request_metrics, "_pending", pending)
    monkeypatch.setattr(request_metrics, "_stop", stopped)
    monkeypatch.setattr(request_metrics, "connect", DB)
    request_metrics.enqueue("GET", "/health", 200, 1)
    request_metrics._worker()
    assert len(statements) == 2
    assert "INTERVAL '7 days'" in statements[1]


@pytest.mark.parametrize("declared", [False, True])
def test_oversized_body_is_rejected_before_handler(declared):
    import asyncio

    from app.body_limit import BodyLimitMiddleware
    called = []
    sent = []
    async def handler(scope, receive, send):
        called.append(True)
    async def receive():
        return {"type": "http.request", "body": b"12345", "more_body": False}
    async def send(message):
        sent.append(message)
    headers = [(b"content-length", b"5")] if declared else []
    middleware = BodyLimitMiddleware(handler, max_upload_bytes=4, max_json_bytes=4)
    asyncio.run(middleware({"type":"http", "method":"POST", "headers":headers}, receive, send))
    assert not called
    assert sent[0]["status"] == 413


def test_body_guard_replays_chunks_exactly():
    import asyncio

    from app.body_limit import BodyLimitMiddleware
    chunks = iter([b"123", b"456"])
    captured = []
    async def receive():
        data = next(chunks)
        return {"type":"http.request", "body":data, "more_body":data == b"123"}
    async def send(message):
        pass
    async def handler(scope, receive, send):
        while True:
            message = await receive()
            captured.append(message["body"])
            if not message["more_body"]:
                break
    asyncio.run(BodyLimitMiddleware(handler, 10, 10)({"type":"http", "method":"POST", "headers":[]}, receive, send))
    assert b"".join(captured) == b"123456"
