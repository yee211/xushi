"""Regression tests for school refresh isolation and nonblocking metrics."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from starlette.requests import Request
from starlette.responses import Response

from app.services import academic


def test_cached_query_does_not_wait_for_refresh(monkeypatch):
    key = (academic._generation, "student01", "2026-2027-1")
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(academic, "_cache", {key: (time.monotonic(), {"courses": []})})
    monkeypatch.setattr(academic, "_refresh_locks", {key: [lock, 1]})
    assert academic.get_schedule("student01", "2026-2027-1")["cached"]


def test_different_students_can_refresh_independently(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(academic, "_cache", {})
    monkeypatch.setattr(academic, "_refresh_locks", {})
    def fetch(sid, term, refresh):
        if sid == "student01":
            entered.set()
            assert release.wait(3)
        return {"student": sid}
    monkeypatch.setattr(academic, "_get_schedule", fetch)
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(academic.get_schedule, "student01", "2026-2027-1", True)
        try:
            assert entered.wait(2)
            second = executor.submit(academic.get_schedule, "student02", "2026-2027-1", True)
            assert second.result(timeout=1)["student"] == "student02"
        finally:
            release.set()
        first.result(timeout=2)
    assert not academic._refresh_locks


def test_same_student_concurrent_forced_refresh_shares_result(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(academic, "_cache", {})
    monkeypatch.setattr(academic, "_refresh_locks", {})
    key = (academic._generation, "student01", "2026-2027-1")
    def fetch(sid, term, refresh):
        calls.append(sid)
        entered.set()
        assert release.wait(3)
        with academic._lock:
            academic._cache[key] = (time.monotonic(), {"complete": True})
        return {"complete": True}
    monkeypatch.setattr(academic, "_get_schedule", fetch)
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(academic.get_schedule, "student01", "2026-2027-1", True)
        try:
            assert entered.wait(2)
            second = executor.submit(academic.get_schedule, "student01", "2026-2027-1", True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with academic._lock:
                    if academic._refresh_locks[key][1] == 2:
                        break
                time.sleep(0.01)
            else:
                raise AssertionError("Second refresh did not join")
        finally:
            release.set()
        assert first.result(timeout=2)["complete"]
        assert second.result(timeout=2)["cached"]
    assert calls == ["student01"] and not academic._refresh_locks


def test_metrics_are_queued_without_waiting_for_database(monkeypatch):
    import queue

    from app import main
    from app.services import request_metrics

    pending = queue.Queue(maxsize=1)
    monkeypatch.setattr(request_metrics, "_pending", pending)
    monkeypatch.setattr(main, "is_pool_ready", lambda: True)

    def forbidden_connect():
        raise AssertionError("Request must not wait for a database connection")

    monkeypatch.setattr(main, "connect", forbidden_connect)

    async def run():
        async def respond(request):
            return Response(status_code=200)
        return await main.request_metrics(Request({"type": "http", "method": "GET", "path": "/api/test", "headers": []}), respond)

    assert asyncio.run(run()).status_code == 200
    method, path, status, duration = pending.get_nowait()
    assert (method, path, status) == ("GET", "/api/test", 200)
    assert duration >= 0
