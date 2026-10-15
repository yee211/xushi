"""Fault injection for final-reply delivery; all external I/O is isolated."""
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.channels.weixin import store, worker
from app.channels.weixin.protocol import InboundText
from app.services import academic_sync_notifications as notifications
from tests.test_academic_sync_notifications import make_delivery


@pytest.fixture
def delivery(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    monkeypatch.setattr(worker, "connect", lambda: db)
    monkeypatch.setattr(worker, "claim_message", lambda *args: True)
    monkeypatch.setattr(worker, "complete_message", MagicMock())
    replies = {}
    monkeypatch.setattr(worker, "load_reply", lambda db, a, m: replies.get((a, m)))
    def save(db, a, m, text):
        return replies.setdefault((a, m), text)
    monkeypatch.setattr(worker, "save_reply", save)
    limiter = MagicMock()
    limiter.hit.return_value = (True, 0)
    monkeypatch.setattr(worker, "clawbot_limiter", limiter)
    agent = MagicMock(return_value="已查询到课程")
    monkeypatch.setattr(worker, "build_agent_reply", agent)
    client = MagicMock()
    message = InboundText("bot", "sender", "message", "明天有什么课", "context", datetime.now(UTC), "run")
    return client, message, agent, limiter, replies


def test_send_timeout_retries_frozen_reply_without_agent_or_rate_limit(delivery):
    client, message, agent, limiter, replies = delivery
    client.send_text.side_effect = TimeoutError("ambiguous network send")
    assert worker.process_message(client, message) is False
    first = client.send_text.call_args
    assert replies[("bot", "message")] == "已查询到课程"
    client.send_text.side_effect = None
    assert worker.process_message(client, message) is True
    assert client.send_text.call_args == first
    agent.assert_called_once()
    limiter.hit.assert_called_once()


def test_restart_resumes_saved_reply_without_executing_sync(delivery):
    client, message, agent, limiter, replies = delivery
    replies[("bot", "message")] = "课表同步任务已提交"
    agent.side_effect = AssertionError("must not enqueue twice")
    assert worker.process_message(client, message)
    assert client.send_text.call_args.args[1] == "课表同步任务已提交"
    agent.assert_not_called()
    limiter.hit.assert_not_called()


def test_persistence_failure_never_sends_unrecoverable_reply(delivery, monkeypatch):
    client, message, agent, limiter, replies = delivery
    def fail(*args):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(worker, "save_reply", fail)
    assert not worker.process_message(client, message)
    client.send_text.assert_not_called()


def test_completed_duplicate_does_not_send_again(delivery, monkeypatch):
    client, message, agent, limiter, replies = delivery
    monkeypatch.setattr(worker, "claim_message", lambda *args: False)
    assert worker.process_message(client, message)
    client.send_text.assert_not_called()
    agent.assert_not_called()


def test_result_ids_remain_isolated_by_account_and_message(delivery):
    client, message, agent, limiter, replies = delivery
    replies[("other-bot", "message")] = "other user's result"
    assert worker.process_message(client, message)
    assert client.send_text.call_args.args[1] == "已查询到课程"
    agent.assert_called_once()


def test_store_refuses_to_deliver_without_persisted_row():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    with pytest.raises(RuntimeError):
        store.save_reply(db, "bot", "message", "answer")


def test_plain_notification_lost_lease_cannot_send(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    account = db.execute.return_value.fetchone.return_value
    db.execute.return_value.fetchone.side_effect = [account, None]
    notifications.deliver(row, {"state":"succeeded"})
    client.send_text.assert_not_called()
    finish.assert_not_called()


def test_plain_notification_persists_before_send(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    events = []
    result = db.execute.return_value
    def execute(sql, params):
        if "SET delivery_text" in sql:
            events.append("save")
        return result
    db.execute.side_effect = execute
    client.send_text.side_effect = lambda *args, **kwargs: events.append("send")
    notifications.deliver(row, {"state":"failed", "error_code":"upstream_timeout"})
    assert events == ["save", "send"]
    finish.assert_called_once_with(row, "sent")


def test_sync_replay_reuses_original_terminal_job_after_cooldown(monkeypatch):
    from app.services import academic_jobs
    db = MagicMock()
    db.__enter__.return_value = db
    binding = {"student":{"id":"student"}, "revision":1, "updated_at":"bound-at"}
    prior = dict.fromkeys(("id","term","state","attempts","result","error","created_at","updated_at","phase","started_at"))
    prior.update(id="original-job", user_id=7, state="succeeded", term="2026-2027-1",
                 student_id="student", binding_revision=1, binding_updated_at="bound-at", refresh=True)
    db.execute.return_value.fetchone.side_effect = [binding, prior]
    monkeypatch.setattr(academic_jobs, "connect", lambda: db)
    monkeypatch.setattr(academic_jobs.academic_binding, "lock_user", MagicMock())
    monkeypatch.setattr(notifications, "subscribe", lambda *args: False)
    target = {"provider":"weixin_ilink", "sender_id":"sender", "account_id":"bot", "message_id":"original-message"}
    result = academic_jobs.enqueue(7, "2026-2027-1", True, cooldown_seconds=30, notification_target=target)
    assert result["id"] == "original-job"
    assert not any("INSERT INTO academic_sync_jobs" in call.args[0] for call in db.execute.call_args_list)


def test_send_succeeded_but_ack_failed_retries_same_reply(delivery, monkeypatch):
    client, message, agent, limiter, replies = delivery
    completion = MagicMock(side_effect=[RuntimeError("commit failed"), None, None])
    monkeypatch.setattr(worker, "complete_message", completion)
    assert not worker.process_message(client, message)
    sent = client.send_text.call_args
    assert worker.process_message(client, message)
    assert client.send_text.call_args == sent
    agent.assert_called_once()
