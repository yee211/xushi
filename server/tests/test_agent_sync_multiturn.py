"""Offline multi-turn flows through real service, history, loop and notification handlers.
Only database, Redis, model HTTP and channel delivery are simulated.
"""
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import HumanMessage

from app.agent import conversation, loop, orchestrator, service
from app.agent.circuit_breaker import llm_circuit_breaker
from app.agent.sync import status_requested
from app.services import academic_jobs
from app.services import academic_sync_notifications as notices
from tests.fakes import FakeAgentDb, FakeResult
from tests.test_agent_conversation import FakeRedis
from tests.test_agent_loop import FakeResponse, reply_message, tool_call


@pytest.mark.parametrize(("state", "phase", "error", "expected"), [
    ("queued", "queued", None, "正在后台排队"),
    ("queued", "retrying", "upstream_timeout", "自动重试"),
    ("running", "querying", None, "正在后台同步"),
    ("running", "writing", None, "正在保存"),
    ("succeeded", "completed", None, "同步成功"),
    ("failed", "failed", "connection_expired", "管理员重新连接"),
])
def test_status_does_not_invoke_model(monkeypatch, state, phase, error, expected):
    tools = MagicMock()
    tools.get_schedule_status.return_value = {"school_bound": True, "sync_job": {
        "id": "job-1", "state": state, "phase": phase, "error_code": error}}
    model = MagicMock(side_effect=AssertionError("status must not invoke a model"))
    monkeypatch.setattr(orchestrator, "run_agent", model)
    result = orchestrator.handle_message("同步好了吗", tools)
    assert expected in result["answer"]
    assert result["resolved_context"]["job_state"] == state
    if state != "succeeded":
        assert "同步成功" not in result["answer"]
    tools.sync_schedule.assert_not_called()
    model.assert_not_called()


def test_status_unavailable_never_submits_or_calls_model(monkeypatch):
    tools = MagicMock()
    tools.get_schedule_status.side_effect = RuntimeError("unavailable")
    model = MagicMock()
    monkeypatch.setattr(orchestrator, "run_agent", model)
    result = orchestrator.handle_message("课表更新了吗", tools)
    assert "暂时无法查询" in result["answer"]
    tools.sync_schedule.assert_not_called()
    model.assert_not_called()


def test_status_followup_uses_recent_context_but_mixed_course_query_does_not():
    history = [HumanMessage(content='同步课表 [已解析上下文：{"intent":"SYNC_SCHEDULE"}]')]
    assert status_requested("好了吗？", history)
    assert not status_requested("好了吗？", [])
    assert not status_requested("刚才同步完，明天有几节课", history)
    assert not status_requested("课表同步后，明天天气怎么样", history)


class ScenarioDb(FakeAgentDb):
    def __init__(self):
        schedule = {"id": 1, "user_id": 7, "name": "评测课表", "term": "2026-2027-1",
                    "start_date": date(2026, 9, 7), "end_date": date(2027, 1, 24),
                    "variant_type": "original", "source_schedule_id": None}
        course = {"id": 11, "name": "高数", "teacher": "张华", "room": "A101", "weekday": 4,
                  "start_section": 1, "end_section": 2, "weeks": list(range(1, 25))}
        super().__init__(identity_user_id=7, schedules=[schedule], courses=[course])
        self.job = None
        self.submissions = 0
        self.status_owners = []

    def execute(self, sql, params=None):
        if "UPDATE academic_sync_notifications SET delivery_text" in sql:
            assert params[1:] == ("notice-1", "lease-1")
            return FakeResult([{"id": "notice-1"}])
        if "FROM user_identities u JOIN channel_accounts" in sql:
            assert params == (7, "weixin_ilink", "sender", "bot")
            return FakeResult([{"context_token": "context", "bot_token_encrypted": "encrypted",
                                "api_base_url": "https://ilinkai.weixin.qq.com", "admin_user_id": ""}])
        if "AS snapshot" in sql:
            return super().execute(sql, params)
        if "FROM academic_bindings" in sql:
            assert params == (7,)
            return FakeResult([{"student": {"default_term": "2026-2027-1"}, "last_synced_term": "2026-2027-1",
                                "last_synced_at": None}])
        if "FROM academic_sync_jobs" in sql:
            self.status_owners.append(params[0])
            return FakeResult([dict(self.job)] if self.job else [])
        if "FROM schedules" in sql and len(params) == 1:
            assert params == (7,)
            return FakeResult(self.schedules)
        return super().execute(sql, params)

    def enqueue(self, user_id, term, refresh, **options):
        assert user_id == 7 and refresh is True and term == "2026-2027-1"
        assert options["notification_target"]["sender_id"] == "sender"
        if self.job is None:
            self.submissions += 1
            self.job = {"id": "job-1", "state": "queued", "phase": "queued", "term": term,
                        "error_code": None, "result": None, "notification_registered": True}
        return dict(self.job)


@pytest.fixture
def flow(monkeypatch):
    db = ScenarioDb()
    redis = FakeRedis()
    monkeypatch.setattr(conversation, "_client", lambda: redis)
    monkeypatch.setattr(academic_jobs, "enqueue", db.enqueue)
    monkeypatch.setattr(loop, "agent_config", lambda: ("https://model.example/v1", "fake-key", "fake-model"))
    monkeypatch.setattr(loop, "get_llm_config", lambda purpose: {})
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: True)
    monkeypatch.setattr(orchestrator, "run_agent", loop.run)
    legacy = orchestrator._fallback_reply
    monkeypatch.setattr(orchestrator, "_fallback_reply", lambda message, tools, history=None, **kwargs:
                        legacy(message, tools, history, allow_llm=False))
    responses, requests = [], []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        assert responses, "unexpected model request"
        return FakeResponse(responses.pop(0))
    monkeypatch.setattr(loop, "_post_llm", post)
    client = MagicMock()
    monkeypatch.setattr(notices, "connect", lambda: db)
    monkeypatch.setattr(notices, "decrypt_token", lambda value: "fake-token")
    monkeypatch.setattr(notices, "ILinkClient", lambda credentials: client)
    finish = MagicMock()
    monkeypatch.setattr(notices, "finish", finish)
    llm_circuit_breaker.reset()
    now = datetime(2026, 10, 14, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    def say(message):
        return service.build_agent_reply(lambda: db, message, "weixin_ilink", "sender", now,
                                         account_id="bot", message_id="inbound-1")
    yield db, redis, responses, requests, client, finish, say
    llm_circuit_breaker.reset()


@pytest.mark.parametrize(("outcome", "unchanged", "room"), [
    ("succeeded", False, "A201"), ("succeeded", True, "A101"), ("failed", False, "A101"),
])
def test_submit_notify_query_and_room_followup(flow, outcome, unchanged, room):
    db, redis, responses, requests, client, finish, say = flow
    assert "已提交" in say("同步课表")
    assert "已提交" in say("再同步课表")
    assert db.submissions == 1
    assert "排队" in say("好了吗？")
    assert not requests
    db.job.update(state=outcome, phase="completed" if outcome == "succeeded" else "failed",
                  error_code="connection_expired" if outcome == "failed" else None,
                  result={"unchanged": unchanged})
    db.courses[0]["room"] = room
    row = {"id": "notice-1", "user_id": 7, "sender_id": "sender", "provider": "weixin_ilink",
           "account_id": "bot", "attempts": 1, "lease_id": "lease-1"}
    notices.deliver(row, db.job)
    notification = client.send_text.call_args.args[1]
    status_answer = say("同步好了吗")
    assert status_answer == notification
    assert ("没有变化" in notification) is (outcome == "succeeded" and unchanged)
    if outcome == "failed":
        assert "管理员重新连接" in notification
    finish.assert_called_once_with(row, "sent")
    assert not requests
    responses.extend([
        reply_message(tool_calls=[tool_call("day-1", "query_day_courses", '{"date":"2026-10-15"}')]),
        reply_message(content=f"明天有高数课，教室是{room}。"),
        reply_message(tool_calls=[tool_call("day-2", "query_day_courses", '{"date":"2026-10-15"}')]),
        reply_message(content=f"高数在{room}。"),
    ])
    assert room in say("明天有几节课")
    followup = say("教室呢")
    assert room in followup and "同步" not in followup
    assert len(requests) == 4 and not responses
    assert all(user == 7 for user in db.status_owners)
    assert any("2026-10-15" in str(message["content"]) for message in requests[2]["messages"])
    assert conversation.load_history(8, "weixin_ilink", "sender") == []


def test_contradictory_model_answer_falls_back_after_success(flow):
    db, redis, responses, requests, client, finish, say = flow
    say("同步课表")
    db.job.update(state="succeeded", result={"unchanged": True})
    assert "同步成功" in say("同步好了吗")
    responses.extend([
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-10-15"}')]),
        reply_message(content="明天有高数课，刚才的同步没有提交成功。"),
    ])
    answer = say("明天有几节课")
    assert "高数" in answer and "A101" in answer
    assert "没有提交成功" not in answer
    assert db.submissions == 1
