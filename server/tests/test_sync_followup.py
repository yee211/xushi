from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent import sync_followup
from app.agent.sync import reply
from app.services import academic_sync_followup as continuation
from app.services import academic_sync_notifications as notifications
from tests.test_academic_sync_notifications import make_delivery

NOW = datetime.now(ZoneInfo("Asia/Shanghai"))


@pytest.mark.parametrize(("message", "kind", "offset", "period"), [
    ("同步一下课表，看看明天有什么课", "day", 1, "all"),
    ("先同步课表，完成后看看明天下午有什么课", "day", 1, "afternoon"),
    ("更新课表后帮我查后天的课", "day", 2, "all"),
    ("同步课表，查下周课表", "week", None, "all"),
])
def test_freeze_supported_query_dates(monkeypatch, message, kind, offset, period):
    now = datetime(2026, 10, 15, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    plan = sync_followup.FollowupPlan.model_validate(sync_followup.prepare(message, now))
    assert plan.kind == kind and plan.period == period
    assert plan.target_date.isoformat() == ("2026-10-19" if offset is None else
                                          (now + timedelta(days=offset)).date().isoformat())


@pytest.mark.parametrize("message", [
    "明天有什么课", "同步课表", "不要同步课表", "同步课表，明天和后天有什么课",
    "同步课表，看看明天下不下雨", "同步课表，看看明天有没有高数课", "同步课表，别查明天的课",
    "同步课表，看看明天有什么课，再查天气", "同步课表，查下周三和周四的课",
    "同步课表，看看明天上午到下午有什么课", "同步课表，查下周上午有什么课",
])
def test_unsupported_queries_never_promise_continuation(monkeypatch, message):
    assert sync_followup.prepare(message, NOW) is None


def test_followup_requires_timezone_but_no_engine_switch():
    assert sync_followup.prepare("同步课表，看看明天有什么课", NOW) is not None
    assert sync_followup.prepare("同步课表，看看明天有什么课", NOW.replace(tzinfo=None)) is None


def make_plan():
    return sync_followup.FollowupPlan(kind="day", target_date=NOW.date(), requested_at=NOW,
                                    question="今天有什么课").model_dump(mode="json")


def test_submission_only_promises_registered_followup():
    base = {"ok": True, "state": "queued", "notification_registered": True}
    assert "请再询问" in reply(base, "同步课表看看明天有什么课")["answer"]
    text = reply(dict(base, followup_registered=True), "同步课表看看明天有什么课")["answer"]
    assert "接着查询" in text and "请再询问" not in text


@pytest.fixture
def resumed(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchone.return_value = {"exists": 1}
    monkeypatch.setattr(continuation, "connect", lambda: db)
    query = MagicMock(return_value="• 08:20–10:00 示例课程，示例教师，A101")
    monkeypatch.setattr(continuation, "answer", query)
    row = {"id": "notice", "user_id": 7, "attempts": 1, "followup": make_plan(), "delivery_text": None}
    job = {"state": "succeeded", "result": {"schedule_id": 12}, "student_id": "student",
           "binding_revision": 3, "binding_updated_at": NOW}
    return db, query, row, job


def test_success_queries_synced_schedule_with_no_sync_permission(resumed):
    db, query, row, job = resumed
    text = continuation.delivery_text(row, job)
    assert "同步成功" in text and "08:20–10:00" in text
    tools = query.call_args.args[1]
    assert tools.context.user_id == 7 and tools.context.default_schedule_id == 12
    assert tools.context.notification_target is None and not tools.sync_authorized
    assert db.execute.call_args.args[1] == (7, "student", 3, NOW, 12)


def test_failed_sync_never_reads_old_courses(resumed):
    db, query, row, job = resumed
    job.update(state="failed", error_code="upstream_timeout")
    text = continuation.delivery_text(row, job)
    assert "查询超时" in text and "没有继续查询" in text
    query.assert_not_called()
    db.execute.assert_not_called()


def test_cached_answer_is_reused_but_binding_is_checked_again(resumed):
    db, query, row, job = resumed
    row["delivery_text"] = "cached payload"
    assert continuation.delivery_text(row, job) == "cached payload"
    query.assert_not_called()
    db.execute.return_value.fetchone.return_value = None
    assert "绑定或课表已发生变化" in continuation.delivery_text(row, job)
    query.assert_not_called()


@pytest.mark.parametrize("mutation", ["invalid", "expired", "missing_schedule"])
def test_invalid_or_disabled_resume_never_queries(monkeypatch, resumed, mutation):
    db, query, row, job = resumed
    if mutation == "invalid":
        row["followup"] = {"kind": "delete_schedule"}
    elif mutation == "expired":
        row["followup"]["requested_at"] = (NOW - timedelta(days=2)).isoformat()
    elif mutation == "missing_schedule":
        job["result"] = {}
    assert "同步成功" in continuation.delivery_text(row, job)
    query.assert_not_called()


def test_transient_query_failure_retries_bounded_by_notification_attempts(resumed):
    db, query, row, job = resumed
    query.side_effect = TimeoutError("private")
    with pytest.raises(TimeoutError):
        continuation.delivery_text(row, job)
    row["attempts"] = 3
    text = continuation.delivery_text(row, job)
    assert "查询暂时不可用" in text and "private" not in text


def test_delivery_persists_payload_before_send_and_honors_lease(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    row["followup"] = make_plan()
    monkeypatch.setattr(continuation, "delivery_text", lambda *args: "rendered payload")
    events = []
    result = db.execute.return_value
    def execute(sql, params):
        if "SET delivery_text" in sql:
            events.append("save")
        return result
    db.execute.side_effect = execute
    client.send_text.side_effect = lambda *args, **kwargs: events.append("send")
    notifications.deliver(row, {"state": "succeeded"})
    assert events == ["save", "send"]
    client.send_text.assert_called_once_with("sender", "rendered payload", "latest-context", client_id="sync_notice-1")
    finish.assert_called_once_with(row, "sent")


def test_lost_lease_does_not_send(monkeypatch):
    db, client, finish, row = make_delivery(monkeypatch)
    account = db.execute.return_value.fetchone.return_value
    db.execute.return_value.fetchone.side_effect = [account, None]
    row["followup"] = make_plan()
    monkeypatch.setattr(continuation, "delivery_text", lambda *args: "payload")
    notifications.deliver(row, {"state": "succeeded"})
    client.send_text.assert_not_called()
    finish.assert_not_called()


def test_graph_resumes_frozen_date_across_midnight_without_model(monkeypatch):
    from app.agent.tools import AgentContext
    from tests.test_agent_loop import make_tools
    tools = make_tools()
    old = datetime(2026, 9, 8, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    plan = sync_followup.FollowupPlan.model_validate(sync_followup.prepare("同步课表，看看明天有什么课", old))
    tools.context = AgentContext(7, old + timedelta(minutes=2))
    text = sync_followup.answer(plan, tools)
    assert "今天（9月9日" in text and "14:00–15:40" in text


def test_graph_rejects_wrong_target_date():
    tools = MagicMock()
    tools.context.now = NOW
    tools.context.default_schedule_id = None
    tools.get_courses_by_date.return_value = {"date": (NOW + timedelta(days=1)).date().isoformat(), "courses": []}
    with pytest.raises(ValueError, match="date mismatch"):
        sync_followup.answer(sync_followup.FollowupPlan.model_validate(make_plan()), tools)


def test_channel_entry_registers_query_atomically_before_promising(monkeypatch):
    from dataclasses import replace

    from app.agent import orchestrator
    from app.services import academic_jobs
    from tests.test_agent_sync import tools_with_binding

    tools = tools_with_binding({"student": {}, "last_synced_term": "2026-2027-1"})
    target = {"provider": "weixin_ilink", "sender_id": "sender", "account_id": "bot", "message_id": "m1"}
    tools.context = replace(tools.context, now=NOW, notification_target=target)
    enqueue = MagicMock(return_value={"id": "job", "state": "queued", "term": "2026-2027-1",
                                      "notification_registered": True, "followup_registered": True})
    monkeypatch.setattr(academic_jobs, "enqueue", enqueue)
    model = MagicMock(side_effect=AssertionError("submission must not wait for model"))
    monkeypatch.setattr(orchestrator, "run_agent", model)
    result = orchestrator.handle_message("同步一下课表，看看明天有什么课", tools)
    frozen = enqueue.call_args.kwargs["notification_target"]["followup"]
    assert frozen["target_date"] == (NOW + timedelta(days=1)).date().isoformat()
    assert "接着查询" in result["answer"]
    assert "followup" not in target
    model.assert_not_called()


def test_weekly_graph_uses_existing_validated_renderer():
    from tests.test_agent_loop import make_tools
    tools = make_tools()
    plan = sync_followup.FollowupPlan(kind="week", target_date="2026-09-07",
                                    requested_at=tools.context.now, question="本周课表")
    text = sync_followup.answer(plan, tools)
    assert "2026-09-07～2026-09-13" in text and "• 14:00–15:40 高数" in text


def test_graph_does_not_fall_back_to_another_schedule():
    tools = MagicMock()
    tools.context.default_schedule_id = 12
    tools.get_courses_by_date.return_value = {"date": NOW.date().isoformat(), "schedule_id": 99, "courses": []}
    with pytest.raises(ValueError, match="schedule mismatch"):
        sync_followup.answer(sync_followup.FollowupPlan.model_validate(make_plan()), tools)
