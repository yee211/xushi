from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.channels.weixin import store, worker
from app.channels.weixin.client import ILinkError
from app.channels.weixin.protocol import Credentials
from app.routers import agent


@pytest.mark.parametrize("connected", [True, False])
def test_binding_status_uses_live_account_state(monkeypatch, connected):
    db = MagicMock()
    db.__enter__.return_value = db
    now = datetime(2026, 10, 14)
    db.execute.return_value.fetchall.return_value = [
        {"provider": "weixin_ilink", "created_at": now, "last_seen_at": now, "connected": connected}]
    monkeypatch.setattr(agent, "connect", lambda: db)
    result = agent.agent_binding_status({"id": 7})
    channels = {item["provider"]: item for item in result["channels"]}
    assert channels["weixin_ilink"]["bound"] is connected
    assert not any("DELETE" in call.args[0] for call in db.execute.call_args_list)


def test_missing_account_is_disconnected(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr(agent, "connect", lambda: db)
    assert not agent.agent_binding_status({"id": 7})["bound"]


@pytest.mark.parametrize(("current_token", "expected"), [("old-token", True), ("new-token", False)])
def test_old_poller_cannot_expire_fresh_login(monkeypatch, current_token, expected):
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [{"bot_token_encrypted": "encrypted"}, {"account_id": "bot"}]
    monkeypatch.setattr(store, "decrypt_token", lambda value: current_token)
    credentials = Credentials("bot", "old-token", "https://ilinkai.weixin.qq.com")
    assert store.mark_session_expired(db, credentials) is expected
    assert db.execute.call_count == (2 if expected else 1)
    if expected:
        assert "status='expired'" in db.execute.call_args.args[0]


def test_expired_poller_persists_state_and_exits(monkeypatch):
    client = MagicMock()
    client.get_updates.side_effect = ILinkError("session timeout", code="-14")
    monkeypatch.setattr(worker, "ILinkClient", lambda credentials: client)
    monkeypatch.setattr(worker, "_running", True)
    db = MagicMock()
    db.__enter__.return_value = db
    monkeypatch.setattr(worker, "connect", lambda: db)
    mark = MagicMock(return_value=True)
    monkeypatch.setattr(worker, "mark_session_expired", mark)
    credentials = Credentials("bot", "old-token", "https://ilinkai.weixin.qq.com")
    assert worker.poll_account(credentials, "cursor") == "cursor"
    mark.assert_called_once_with(db, credentials)
    client.get_updates.assert_called_once()
    client.close.assert_called_once()


def test_expiry_storage_failure_retries_without_losing_detection(monkeypatch):
    import threading

    client = MagicMock()
    client.get_updates.side_effect = ILinkError("session timeout", code="-14")
    monkeypatch.setattr(worker, "ILinkClient", lambda credentials: client)
    monkeypatch.setattr(worker, "_running", True)
    db = MagicMock()
    db.__enter__.return_value = db
    monkeypatch.setattr(worker, "connect", lambda: db)
    mark = MagicMock(side_effect=RuntimeError("storage unavailable"))
    monkeypatch.setattr(worker, "mark_session_expired", mark)
    stop = threading.Event()
    def wait(seconds):
        assert seconds == 10
        stop.set()
    monkeypatch.setattr(stop, "wait", wait)
    worker.poll_account(Credentials("bot", "old-token", "https://ilinkai.weixin.qq.com"), "cursor", stop)
    mark.assert_called_once()


def test_fresh_scan_restores_active_account(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(store, "encrypt_token", lambda value: "encrypted-new-token")
    store.save_account(db, Credentials("bot", "new-token", "https://ilinkai.weixin.qq.com"), 7)
    assert "status='active'" in db.execute.call_args.args[0]
