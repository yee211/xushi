"""Completion regressions: no real providers, database or channel delivery."""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.agent import graph, loop, orchestrator
from app.agent.completion import Completion, finalize
from app.agent.sync import reply, status_requested
from tests.test_agent_graph import replay, isolated_engine  # noqa: F401
from tests.test_agent_loop import make_tools, reply_message, tool_call


def test_schema_requires_a_task_for_pending():
    with pytest.raises(ValidationError):
        Completion(status="pending", answer="处理中")


def test_screenshot_latest_question_bypasses_model(monkeypatch):
    tools = make_tools()
    tools.get_schedule_status = MagicMock(return_value={"school_bound": True,
        "last_synced_at": "2026-10-15T12:30:00+08:00", "sync_job": {"state": "succeeded"}})
    model = MagicMock(side_effect=AssertionError("status question must bypass model"))
    monkeypatch.setattr(orchestrator, "run_agent", model)
    history = [HumanMessage(content="更新课表然后查一下明天课表"),
               AIMessage(content="同步成功，明天有一节课")]
    result = orchestrator.handle_message("课表已经是最新的了吗", tools, history)
    assert result["status"] == "completed"
    assert "12:30" in result["answer"]
    assert "再次同步确认" in result["answer"]
    assert "稍等" not in result["answer"]
    tools.get_schedule_status.assert_called_once()
    model.assert_not_called()


@pytest.mark.parametrize("question", ["课表是最新的吗", "需要更新课表吗", "要不要更新课表", "上次什么时候同步"])
def test_freshness_question_is_read_only(question):
    assert status_requested(question)


def test_promise_continues_to_tool_and_returns_courses(monkeypatch):
    result, requests, _ = replay(monkeypatch, "明天有什么课", [
        reply_message(content="我帮你看看，稍等一下"),
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":""}')])
    assert "高数" in result["answer"]
    assert "稍等" not in result["answer"]
    assert len(requests) == 3


def test_repeated_promise_stops_without_pretending_to_run(monkeypatch):
    result, requests, _ = replay(monkeypatch, "明天有什么课", [
        reply_message(content="我帮你看看，稍等一下"),
        reply_message(content="稍等一下")])
    assert result is None
    assert len(requests) == 2


def test_course_comment_cannot_promise_unregistered_work(monkeypatch):
    result, requests, _ = replay(monkeypatch, "明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":"稍等，我一会告诉你"}')])
    assert "高数" in result["answer"] and "稍等" not in result["answer"]
    assert len(requests) == 2


def test_fabricated_pending_id_does_not_create_background_work(monkeypatch):
    result, requests, _ = replay(monkeypatch, "你好", [
        reply_message(content='{"status":"pending","answer":"处理中","task_id":"invented"}'),
        reply_message(content="在的，可以帮你查课表")])
    assert "invented" not in result["answer"]
    assert len(requests) == 2


@pytest.mark.parametrize("registered", [False, True])
def test_sync_pending_uses_real_task_and_registered_notification(registered):
    result = finalize(reply({"ok": True, "state": "queued", "job_id": "job-1",
                             "notification_registered": registered}))
    assert result["status"] == "pending" and result["task_id"] == "job-1"
    assert ("完成后我会" in result["answer"]) == registered


def test_unregistered_followup_never_promises_delivery():
    result = finalize(reply({"ok": True, "state": "queued", "job_id": "job-1",
                             "followup_registered": True, "notification_registered": False}))
    assert "我会接着" not in result["answer"]


def test_failed_submission_has_no_task():
    result = finalize(reply({"ok": False, "error": "submission_unknown", "message": "提交结果暂不确定，请查询同步进度。"}))
    assert result["status"] == "failed" and result["task_id"] is None


def test_fallback_promise_is_rejected_at_shared_exit(monkeypatch):
    monkeypatch.setattr(orchestrator, "_handle_message", lambda *a: {
        "intent": "HELP", "answer": "我帮你看看，稍等一下", "tool_result": None})
    result = orchestrator.handle_message("帮我查课", make_tools())
    assert result["status"] == "failed" and "稍等" not in result["answer"]


def test_normal_query_keeps_two_model_calls(monkeypatch):
    result, requests, _ = replay(monkeypatch, "明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":""}')])
    assert "高数" in result["answer"] and len(requests) == 2


def test_model_requested_to_return_fixed_json_fields(monkeypatch):
    result, requests, _ = replay(monkeypatch, "你好", [reply_message(
        content='{"status":"completed","answer":"在的，可以帮你查课表","task_id":null}')])
    assert result["answer"] == "在的，可以帮你查课表"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "task_id" in requests[0]["messages"][0]["content"]


def test_sync_without_task_id_cannot_be_pending_or_completed():
    result = finalize(reply({"ok": True, "state": "queued", "notification_registered": True}))
    assert result["status"] == "failed" and result["task_id"] is None
    assert "完成后我会" not in result["answer"]


@pytest.mark.parametrize("content", ['{"answer":"稍等"}', '{"status":"completed"}', '[]'])
def test_malformed_schema_never_leaks_json_to_user(monkeypatch, content):
    result, requests, _ = replay(monkeypatch, "你好", [
        reply_message(content=content), reply_message(content="在的，可以帮你查课表")])
    assert result["answer"] == "在的，可以帮你查课表"
    assert len(requests) == 2


def test_empty_courses_are_still_completed_without_extra_call(monkeypatch):
    result, requests, _ = replay(monkeypatch, "明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":"稍等一下"}')], tools=make_tools([]))
    assert "没有课" in result["answer"] and "稍等" not in result["answer"]
    assert len(requests) == 2


def test_failed_tools_produce_failed_completion():
    result = finalize({"intent":"AGENT_LOOP", "answer":"暂时无法查询课表", "tool_result":{
        "skills":[{"skill":"query_day_courses", "result":{"error":"service_unavailable"}}]}})
    assert result["status"] == "failed"


def test_correction_does_not_reset_deadline(monkeypatch):
    from app.agent import budget
    import httpx
    calls = []
    monkeypatch.setattr(loop, "agent_config", lambda: ("https://example.test", "fake", "fake"))
    monkeypatch.setattr(loop, "get_llm_config", lambda scope: {})
    def post(url, **kwargs):
        calls.append(kwargs)
        from tests.test_agent_loop import FakeResponse
        return FakeResponse(reply_message(content="稍等一下"))
    monkeypatch.setattr(loop, "_post_llm", post)
    checks = []
    def remaining():
        checks.append(True)
        if len(checks) > 2:
            raise httpx.TimeoutException("turn budget exhausted")
        return 1
    monkeypatch.setattr(loop, "remaining", remaining)
    assert loop.run(make_tools(), "明天有什么课") is None
    assert len(calls) == 1


def test_schema_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        Completion(status="completed", answer="在的", fake_task=True)


@pytest.mark.parametrize(("status", "answer"), [
    ("failed", "暂时无法查询课表"), ("needs_input", "你想查哪一天？")])
def test_structured_failure_and_clarification_are_not_completed(monkeypatch, status, answer):
    import json
    result, _, _ = replay(monkeypatch, "你好", [reply_message(content=json.dumps(
        {"status":status,"answer":answer,"task_id":None}, ensure_ascii=False))])
    output = finalize(dict(result, intent="AGENT_LOOP"))
    assert output["status"] == status
    assert "_completion_status" not in output
