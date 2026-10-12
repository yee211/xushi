"""Offline tests for the optional cloud browser session maintainer."""
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "scripts" / "academic_session_worker.py"
spec = importlib.util.spec_from_file_location("academic_session_worker", path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Context:
    def cookies(self, urls):
        assert urls == [worker.ENTRY]
        return [{"name": "username", "value": "school-account"}, {"name": "session", "value": "new"}]


class Page:
    def evaluate(self, expression):
        assert expression == "navigator.userAgent"
        return "test-agent"


class Client:
    def __init__(self, headers):
        assert headers["Cookie"] == "username=school-account; session=new"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def grades(self):
        return ["2024"]


def test_verified_renewal_is_saved_without_returning_secrets(monkeypatch):
    saved = []
    monkeypatch.setattr(worker, "CcsutClient", Client)
    monkeypatch.setattr(worker, "connection_headers", lambda: {"Cookie": "old", "User-Agent": "test-agent"})
    monkeypatch.setattr(worker, "save_connection", lambda *args: saved.append(args))
    grades, rotated = worker.export_verified(Context(), Page(), "school-account")
    assert grades == ["2024"] and rotated
    assert len(saved) == 1


def test_wrong_account_never_exports(monkeypatch):
    saved = []
    monkeypatch.setattr(worker, "save_connection", lambda *args: saved.append(args))
    with pytest.raises(ValueError, match="account_mismatch"):
        worker.export_verified(Context(), Page(), "another-account")
    assert not saved


def test_unchanged_session_not_rewritten(monkeypatch):
    monkeypatch.setattr(worker, "CcsutClient", Client)
    monkeypatch.setattr(worker, "connection_headers", lambda: {
        "Cookie": "username=school-account; session=new", "User-Agent": "test-agent"})
    monkeypatch.setattr(worker, "save_connection", lambda *_: pytest.fail("unchanged session rewritten"))
    assert worker.export_verified(Context(), Page(), "school-account") == (["2024"], False)



def test_export_verifies_outside_the_browser_event_loop(monkeypatch):
    import asyncio
    import threading
    owner = threading.get_ident()
    class LoopClient(Client):
        def grades(self):
            assert threading.get_ident() != owner
            with asyncio.Runner() as runner:
                return runner.run(asyncio.sleep(0, result=["2024"]))
    monkeypatch.setattr(worker, "CcsutClient", LoopClient)
    monkeypatch.setattr(worker, "connection_headers", lambda: {"Cookie": "old", "User-Agent": "test-agent"})
    monkeypatch.setattr(worker, "save_connection", lambda *_: None)
    async def browser_context():
        return worker.export_verified(Context(), Page(), "school-account")
    assert asyncio.run(browser_context()) == (["2024"], True)
