"""Regression cases for backend/agent alignment; all providers and storage are fake."""
import json
from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from app.agent import budget, conversation, http_client, loop
from app.agent.tools import ScheduleTools
from app.services.schedule_query import ScheduleQueryError, select_effective_schedule
from tests.test_schedule_query import schedule


def fact(result, skill="query_day_courses"):
    return {"skill": skill, "arguments": '{"date":"2026-09-14"}', "result": result}


def test_course_claims_require_current_facts():
    assert not loop._facts_grounded("明天有高数课", [], "明天有课吗")
    assert not loop._facts_grounded("明天有高数课", [fact({"courses": []})], "明天有课吗")
    assert loop._facts_grounded("明天没有课", [fact({"courses": []})], "明天有课吗")
    assert loop._facts_grounded("暂时无法查询课表", [fact({"error": "service_unavailable"})], "明天有课吗")
    assert not loop._facts_grounded("明天没有课", [fact({"error": "service_unavailable"})], "明天有课吗")
    assert loop._facts_grounded("在的，可以帮你查课表", [], "你好")


def test_failed_tool_does_not_become_resolved_context():
    assert "target_date" not in loop._extract_context_entities([fact({"error": "OUTSIDE_TERM"})])


def test_changed_schedule_drops_old_answers_but_preserves_followup(monkeypatch):
    client = MagicMock()
    client.get.return_value = json.dumps({"messages": [
        {"role": "user", "content": "明天高数在哪", "created_at": "2026-09-13",
         "schedule_version": "old", "resolved_context": {"target_date": "2026-09-14", "course_name": "高数"}},
        {"role": "assistant", "content": "高数在旧教室A101", "schedule_version": "old"}]})
    monkeypatch.setattr(conversation, "_client", lambda: client)
    history = conversation.load_history(1, "wecom", "sender", "new")
    assert len(history) == 1 and "A101" not in history[0].content
    assert "2026-09-14" in history[0].content and "重新查询" in history[0].content


def test_school_schedule_and_explicit_selection():
    manual, school = schedule(1), dict(schedule(2), academic_student_id="student")
    assert select_effective_schedule([manual, school], date(2026, 9, 14))["id"] == 2
    assert select_effective_schedule([manual, school], date(2026, 9, 14), 1)["id"] == 1
    with pytest.raises(ScheduleQueryError, match="使用课表"):
        select_effective_schedule([manual, schedule(3)], date(2026, 9, 14))


def test_queue_wait_consumes_turn_budget(monkeypatch):
    monkeypatch.setattr(http_client, "is_httpx_post_patched", lambda: False)
    semaphore = MagicMock()
    semaphore.acquire.return_value = False
    monkeypatch.setattr(http_client, "get_llm_semaphore", lambda: semaphore)
    with budget.execution(), pytest.raises(httpx.TimeoutException):
        http_client.post_llm("https://example.test", timeout=15)
    semaphore.release.assert_not_called()


def test_snapshot_version_changes_on_course_edit():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {"snapshot": {"courses": [{"room": "A101"}]}},
        {"snapshot": {"courses": [{"room": "B202"}]}}]
    from contextlib import contextmanager

    @contextmanager
    def connection():
        yield db

    tools = ScheduleTools(connection, MagicMock(user_id=1))
    assert tools.schedule_version() != tools.schedule_version()


def test_nonempty_day_cannot_be_rewritten_as_empty_or_wrong_room():
    facts = [fact({"courses": [{"name": "高数", "room": "A101"}]})]
    assert not loop._facts_grounded("明天没有课", facts, "明天有课吗")
    assert not loop._facts_grounded("明天有高数课，在B202", facts, "明天有课吗")
    assert not loop._facts_grounded("明天有《英语》", facts, "明天有课吗")
    assert loop._facts_grounded("明天有高数课，在A101", facts, "明天有课吗")


def test_weather_and_status_require_their_own_tools():
    assert not loop._facts_grounded("同步已完成", [], "同步好了没")
    assert loop._facts_grounded("有已保存的课表", [
        fact({"schedules": [{"id": 1}]}, "get_schedule_status")], "同步好了没")
    assert not loop._facts_grounded("明天晴天", [], "明天天气如何")
    assert not loop._facts_grounded("明天不用带伞", [
        fact({"rain": {"rain": True}}, "get_weather")], "明天带伞吗")
    assert not loop._facts_grounded("明天30度", [
        fact({"rain": {"rain": False}, "daily": {"temp_min": 14, "temp_max": 23}}, "get_weather")], "明天几度")
    assert not loop._facts_grounded("明天晴天", [
        fact({"rain": None, "daily": None}, "get_weather")], "明天天气如何")


def test_deadline_is_shared_and_reset(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("AGENT_TURN_TIMEOUT_SECONDS", "10")
    with budget.execution():
        clock[0] += 7
        with budget.execution():
            assert budget.remaining(15) == 3
        clock[0] += 3
        assert not budget.available()
        with pytest.raises(httpx.TimeoutException):
            budget.remaining()
    assert budget.remaining(15) == 15


def test_model_slot_always_released_on_timeout(monkeypatch):
    monkeypatch.setattr(http_client, "is_httpx_post_patched", lambda: False)
    semaphore, client = MagicMock(), MagicMock()
    semaphore.acquire.return_value = True
    client.post.side_effect = httpx.TimeoutException("timeout")
    monkeypatch.setattr(http_client, "get_llm_semaphore", lambda: semaphore)
    monkeypatch.setattr(http_client, "get_llm_client", lambda: client)
    with budget.execution(), pytest.raises(httpx.TimeoutException):
        http_client.post_llm("https://example.test", timeout=15)
    semaphore.release.assert_called_once()


def test_selection_is_scoped_and_storage_failure_is_honest(monkeypatch):
    from tests.test_agent_conversation import FakeRedis
    client = FakeRedis()
    monkeypatch.setattr(conversation, "_client", lambda: client)
    assert conversation.select_schedule(1, "wecom", "sender", 7)
    assert conversation.selected_schedule(1, "wecom", "sender") == 7
    assert conversation.selected_schedule(2, "wecom", "sender") is None
    assert conversation.selected_schedule(1, "weixin_ilink", "sender") is None
    monkeypatch.setattr(conversation, "_client", lambda: None)
    assert not conversation.select_schedule(1, "wecom", "sender", 8)


def test_cannot_select_another_users_schedule(monkeypatch):
    from app.agent import service
    from tests.fakes import FakeResult

    class Db:
        def execute(self, sql, params):
            if "FROM user_identities" in sql:
                return FakeResult([{"user_id": 1}])
            assert "WHERE id=%s AND user_id=%s" in sql
            assert params == (9, 1)
            return FakeResult([])
    saved = MagicMock()
    monkeypatch.setattr(service, "select_schedule", saved)
    assert "没有找到" in service.build_agent_reply(Db(), "使用课表 9", "wecom", "sender")
    saved.assert_not_called()


def test_weather_skill_exposes_daily_and_validates_period(monkeypatch):
    from datetime import datetime

    from app.agent import skills
    from app.agent.tools import AgentContext
    monkeypatch.setattr(skills, "day_rain", lambda *args: {"rain": False, "peak": 0})
    monkeypatch.setattr(skills, "fetch_daily_weather", lambda *args: {"temp_min": 14, "temp_max": 23})
    tools = ScheduleTools(None, AgentContext(1, datetime(2026, 9, 14)))
    registry = skills.build_skills(tools)
    result = skills.dispatch(registry, "get_weather", '{"date":"2026-09-14"}')
    assert result["daily"]["temp_max"] == 23 and not result["rain"]["rain"]
    assert "error" in skills.dispatch(registry, "get_weather", '{"date":"2026-09-14","period":"invalid"}')


def test_same_version_keeps_assistant_facts(monkeypatch):
    client = MagicMock()
    client.get.return_value = json.dumps({"messages": [
        {"role": "assistant", "content": "高数在A101", "schedule_version": "current"}]})
    monkeypatch.setattr(conversation, "_client", lambda: client)
    assert conversation.load_history(1, "wecom", "sender", "current")[0].content == "高数在A101"


def test_truncated_main_answer_returns_fallback(monkeypatch):
    from tests.test_agent_loop import configure, make_tools
    configure(monkeypatch, [{"choices": [{"finish_reason": "length",
                                         "message": {"content": "部分课程"}}]}])
    assert loop.run(make_tools(), "这周课表") is None


def test_error_phrase_cannot_bypass_fact_guard():
    failed = [fact({"error": "service_unavailable"})]
    assert not loop._facts_grounded("无法查询，不过明天有高数课", failed, "明天有课吗")
    assert not loop._facts_grounded("无法查询，不过高数在A101", failed, "明天有课吗")
    assert not loop._facts_grounded("暂时无法查天气，不过明天晴天", [
        fact({"rain": None, "daily": None}, "get_weather")], "明天天气如何")


def test_temperature_range_validates_both_endpoints():
    facts = [fact({"rain": {"rain": False}, "daily": {"temp_min": 14, "temp_max": 23}}, "get_weather")]
    assert loop._facts_grounded("气温14-23℃", facts, "明天几度")
    assert not loop._facts_grounded("气温5-23℃", facts, "明天几度")


def test_weekly_polish_cannot_drop_a_course():
    from app.agent.polish_ai import _grounded
    result = {"days": [{"courses": [
        {"name": "高数", "start_time": "14:00", "end_time": "15:40"},
        {"name": "英语", "start_time": "16:00", "end_time": "17:40"}]}]}
    answer = "高数14:00–15:40，英语16:00–17:40"
    assert not _grounded("高数14:00–15:40", answer, result)
    assert _grounded(answer, answer, result)
