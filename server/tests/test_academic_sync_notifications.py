from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.agent.sync import reply
from app.services import academic, academic_jobs, academic_runtime
from app.services import academic_sync_notifications as notifications


@pytest.mark.parametrize(("error", "code", "expected"), [
    (academic.AcademicError("connection_expired", "private details", 409), "connection_expired", "管理员重新连接"),
    (academic.AcademicError("term_unavailable", "private", 422), "term_unavailable", "尚未发布"),
    (academic.AcademicError("schedule_invalid", "private", 502), "schedule_invalid", "数据异常"),
    (academic.AcademicError("upstream_timeout", "private", 504), "upstream_timeout", "查询超时"),
    (academic_runtime.SyncTimeout("private"), "sync_timeout", "执行超时"),
    (HTTPException(409, "绑定已变更，请重新同步"), "binding_changed", "绑定发生变化"),
    (HTTPException(409, "请先绑定学校身份"), "school_not_bound", "已解绑"),
    (RuntimeError("private token=secret"), "internal_error", "服务发生异常"),
])
def test_failure_classification_does_not_expose_raw_errors(error, code, expected):
    assert notifications.classify_error(error) == code
    text = notifications.completion_text({"state": "failed", "error_code": code, "error": str(error)})
    assert expected in text
    assert "已保存的课表" in text
    assert "private" not in text and "secret" not in text


def test_only_terminal_states_are_notified():
    assert "最新课表" in notifications.completion_text({"state": "succeeded"})
    assert "没有变化" in notifications.completion_text({"state": "succeeded", "result": {"unchanged": True}})
    for state in ("queued", "running"):
        with pytest.raises(ValueError):
            notifications.completion_text({"state": state})


def test_initial_reply_promises_notification_only_when_registered():
    result = {"ok": True, "state": "queued", "job_id": "job-1", "notification_registered": True}
    assert "再发一条" in reply(result)["answer"]
    assert "再发一条" not in reply(dict(result, notification_registered=False))["answer"]


def make_delivery(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchone.return_value = {"context_token": "latest-context", "bot_token_encrypted": "encrypted",
                                                   "api_base_url": "https://ilinkai.weixin.qq.com", "admin_user_id": ""}
    monkeypatch.setattr(notifications, "connect", lambda: db)
    monkeypatch.setattr(notifications, "decrypt_token", lambda value: "token")
    client = MagicMock()
    monkeypatch.setattr(notifications, "ILinkClient", lambda credentials: client)
    finish = MagicMock()
    monkeypatch.setattr(notifications, "finish", finish)
    row = {"id": "notice-1", "job_id": "job-1", "user_id": 7, "provider": "weixin_ilink",
           "sender_id": "sender", "account_id": "bot", "attempts": 1, "lease_id": "lease"}
    return db, client, finish, row


def test_success_routes_to_original_sender_and_latest_context(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    notifications.deliver(row, {"state": "succeeded"})
    client.send_text.assert_called_once_with("sender", notifications.completion_text({"state": "succeeded"}),
                                             "latest-context", client_id="sync_notice-1")
    assert db.execute.call_args_list[0].args[1] == (7, "weixin_ilink", "sender", "bot")
    finish.assert_called_once_with(row, "sent")
    client.close.assert_called_once()


def test_unbound_or_rotated_account_is_not_notified(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    db.execute.return_value.fetchone.return_value = None
    notifications.deliver(row, {"state": "failed", "error_code": "connection_expired"})
    client.send_text.assert_not_called()
    finish.assert_called_once_with(row, "cancelled", "recipient_unavailable")


@pytest.mark.parametrize(("attempts", "error", "state", "code"), [
    (1, TimeoutError(), "pending", "delivery_failed"),
    (3, TimeoutError(), "failed", "delivery_failed"),
    (1, notifications.ILinkError("expired", code="-14"), "failed", "channel_expired"),
])
def test_delivery_failure_is_bounded_and_independent_of_sync(monkeypatch, attempts, error, state, code):
    db, client, finish, row = make_delivery(monkeypatch)
    row["attempts"] = attempts
    client.send_text.side_effect = error
    job = {"state": "succeeded"}
    notifications.deliver(row, job)
    finish.assert_called_once_with(row, state, code)
    assert job == {"state": "succeeded"}
    client.close.assert_called_once()


def test_submission_and_subscription_share_transaction(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    binding = {"student": {"id": "student"}, "revision": 1, "updated_at": "now"}
    job = dict.fromkeys(("id", "term", "state", "attempts", "result", "error", "created_at", "updated_at", "phase", "started_at"))
    job.update(id="job-1", user_id=7, student_id="student", binding_revision=1,
               binding_updated_at="now", term="2026-2027-1", refresh=True, state="running")
    db.execute.return_value.fetchone.side_effect = [binding, job]
    monkeypatch.setattr(academic_jobs, "connect", lambda: db)
    monkeypatch.setattr(academic_jobs.academic_binding, "lock_user", MagicMock())
    subscribe = MagicMock(return_value=True)
    monkeypatch.setattr(notifications, "subscribe", subscribe)
    target = {"provider": "weixin_ilink", "sender_id": "sender", "account_id": "bot", "message_id": "m1"}
    result = academic_jobs.enqueue(7, "2026-2027-1", True, notification_target=target)
    assert result["notification_registered"]
    subscribe.assert_called_once_with(db, job, target)


def test_other_channels_and_terminal_reuse_do_not_subscribe():
    db = MagicMock()
    target = {"provider": "wecom", "sender_id": "sender", "account_id": "bot", "message_id": "m1"}
    assert not notifications.subscribe(db, {"state": "queued"}, target)
    assert not notifications.subscribe(db, {"state": "succeeded"}, dict(target, provider="weixin_ilink"))
    assert not notifications.subscribe(db, {"state": "queued"}, None)
    db.execute.assert_not_called()


@pytest.mark.parametrize("provider", ["weixin_ilink", "wecom"])
def test_channel_entry_passes_only_supported_notification_target(monkeypatch, provider):
    from app.agent import service
    from app.agent.tools import ScheduleTools

    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchone.return_value = {"user_id": 7}
    monkeypatch.setattr(service, "selected_schedule", lambda *args: None)
    monkeypatch.setattr(ScheduleTools, "schedule_version", lambda self: "version")
    monkeypatch.setattr(service, "load_history", lambda *args: [])
    monkeypatch.setattr(service, "append_turn", MagicMock())
    contexts = []
    def handle(message, tools, history=None):
        contexts.append(tools.context)
        return {"answer": "已提交", "intent": "SYNC_SCHEDULE"}
    monkeypatch.setattr(service, "handle_message", handle)
    service.build_agent_reply(lambda: db, "同步课表", provider, "sender", account_id="bot", message_id="m1")
    expected = {"provider": "weixin_ilink", "sender_id": "sender", "account_id": "bot", "message_id": "m1"}
    assert contexts[0].notification_target == (expected if provider == "weixin_ilink" else None)
