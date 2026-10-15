"""Deterministic parity and failure-isolation checks; never call a real provider."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytest.importorskip("langgraph")

from app.agent import budget, graph, loop, orchestrator  # noqa: E402
from app.agent.circuit_breaker import llm_circuit_breaker  # noqa: E402
from tests.test_agent_loop import FakeResponse, make_tools, reply_message, tool_call  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_engine(monkeypatch):
    monkeypatch.setattr(loop, "agent_config", lambda: ("https://api.deepseek.com/v1", "test-key", "test-model"))
    monkeypatch.setattr(loop, "get_llm_config", lambda scope: {})
    llm_circuit_breaker.reset()
    yield
    llm_circuit_breaker.reset()


def replay(monkeypatch, engine, question, responses, tools=None, history=None):
    replies = list(copy.deepcopy(responses))
    sent = []
    def post(url, **kwargs):
        sent.append(copy.deepcopy(kwargs["json"]))
        assert replies, "unexpected model invocation"
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)
    monkeypatch.setenv("AGENT_ENGINE", engine)
    monkeypatch.setattr(loop, "_post_llm", post)
    llm_circuit_breaker.reset()
    result = loop.run(tools or make_tools(), question, history)
    return result, sent, llm_circuit_breaker.state


@pytest.mark.parametrize(("question", "responses"), [
    ("你好", [reply_message(content="在的，可以帮你查课表")]),
    ("明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":"早点休息吧"}')]),
    ("这周课表", [
        reply_message(tool_calls=[tool_call("week", "query_week_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":""}')]),
    ("明天和后天有什么课", [
        reply_message(tool_calls=[tool_call("d1", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(tool_calls=[tool_call("d2", "query_day_courses", '{"date":"2026-09-10"}')]),
        reply_message(content='{"closing":""}')]),
    ("明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content='{"closing":"同步失败了"}')]),
    ("明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"bad"}')]),
        reply_message(content="暂时无法查询课表")]),
    ("明天有什么课", [httpx.TimeoutException("unavailable")]),
    ("明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        httpx.TimeoutException("unavailable")]),
    ("明天有什么课", [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        {"choices":[{"finish_reason":"length", "message":{"content":"partial"}}]}]),
    ("明天有什么课", [reply_message(tool_calls=[tool_call(str(n), "list_course_catalog", '{}')])
                        for n in range(4)]),
    ("明天有什么课", [reply_message(content="明天有高数课，在B999")]),
])
def test_legacy_and_graph_have_identical_requests_results_and_breaker(monkeypatch, question, responses):
    legacy, old_requests, old_breaker = replay(monkeypatch, "legacy", question, responses)
    migrated, new_requests, new_breaker = replay(monkeypatch, "langgraph", question, responses)
    assert migrated == legacy
    assert new_requests == old_requests
    assert new_breaker == old_breaker
    assert len(new_requests) <= loop.MAX_ROUNDS


def test_empty_timetable_and_history_are_preserved(monkeypatch):
    responses = [reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
                 reply_message(content='{"closing":""}')]
    history = [HumanMessage(content="明天查高数"), AIMessage(content="之前的教室是B999")]
    old, old_requests, _ = replay(monkeypatch, "legacy", "明天有什么课", responses, make_tools([]), history)
    new, new_requests, _ = replay(monkeypatch, "langgraph", "明天有什么课", responses, make_tools([]), history)
    assert old == new and "没有课" in new["answer"]
    assert old_requests == new_requests
    assert new_requests[0]["messages"][1]["content"] == "明天查高数"


def test_parallel_tool_order_and_context_are_preserved(monkeypatch):
    marker = ContextVar("graph_test_marker", default=None)
    token = marker.set("request-context")
    original = loop._execute_tool_call
    seen = []
    def execute(skills, call):
        seen.append(marker.get())
        return original(skills, call)
    monkeypatch.setattr(loop, "_execute_tool_call", execute)
    responses = [reply_message(tool_calls=[
        tool_call("d1", "query_day_courses", '{"date":"2026-09-09"}'),
        tool_call("d2", "query_day_courses", '{"date":"2026-09-10"}')]),
        reply_message(content='{"closing":""}')]
    try:
        old, old_requests, _ = replay(monkeypatch, "legacy", "明天和后天有什么课", responses)
        new, new_requests, _ = replay(monkeypatch, "langgraph", "明天和后天有什么课", responses)
    finally:
        marker.reset(token)
    assert old == new and old_requests == new_requests
    assert seen == ["request-context"] * 4
    assert [message["tool_call_id"] for message in new_requests[1]["messages"] if message["role"] == "tool"] == ["d1", "d2"]


def test_graph_framework_failure_retains_facts_without_replaying_legacy(monkeypatch):
    model = MagicMock(return_value=FakeResponse(reply_message(tool_calls=[
        tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')])))
    monkeypatch.setattr(loop, "_post_llm", model)
    old_loop = MagicMock(side_effect=AssertionError("must not replay old loop"))
    monkeypatch.setattr(loop, "_run", old_loop)
    class BrokenGraph:
        def __init__(self, runtime):
            self.runtime = runtime
        def invoke(self, initial, config):
            state = self.runtime.initialize({})
            state.update(self.runtime.model(state))
            state.update(self.runtime.execute_tools(state))
            raise RuntimeError("framework failure after tools")
    monkeypatch.setattr(graph, "build_graph", BrokenGraph)
    monkeypatch.setenv("AGENT_ENGINE", "langgraph")
    result = loop.run(make_tools(), "明天有什么课")
    assert "• 14:00–15:40 高数，张老师，A101" in result["answer"]
    model.assert_called_once()
    old_loop.assert_not_called()


def test_graph_budget_expiry_does_not_discard_verified_courses(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]))
    monkeypatch.setattr(loop, "_post_llm", post)
    checks = [0]
    def remaining():
        checks[0] += 1
        if checks[0] >= 3:
            raise httpx.TimeoutException("turn budget exhausted")
        return 10
    monkeypatch.setattr(loop, "remaining", remaining)
    monkeypatch.setenv("AGENT_ENGINE", "langgraph")
    assert "高数" in loop.run(make_tools(), "明天有什么课")["answer"]
    assert len(calls) == 1


def test_graph_requests_are_isolated_under_concurrency(monkeypatch):
    monkeypatch.setenv("AGENT_ENGINE", "langgraph")
    def post(url, **kwargs):
        messages = kwargs["json"]["messages"]
        tool_messages = [m for m in messages if m["role"] == "tool"]
        if tool_messages:
            return FakeResponse(reply_message(content='{"closing":""}'))
        current = json.loads(messages[-1]["content"])
        day = current["服务端当前时间"][:10]
        return FakeResponse(reply_message(tool_calls=[tool_call("day", "query_day_courses", json.dumps({"date":day}))]))
    monkeypatch.setattr(loop, "_post_llm", post)
    tools_a, tools_b = make_tools(), make_tools()
    # Distinct factories and course names make any shared closure/state observable.
    tools_a._db_or_factory.courses[0] = dict(tools_a._db_or_factory.courses[0], name="用户甲的课程", weekday=2)
    tools_b._db_or_factory.courses[0] = dict(tools_b._db_or_factory.courses[0], name="用户乙的课程", weekday=3)
    from dataclasses import replace
    tools_b.context = replace(tools_b.context, user_id=2, now=tools_b.context.now + timedelta(days=1))
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(loop.run, tools_a, "今天有什么课")
        b = executor.submit(loop.run, tools_b, "今天有什么课")
    assert "用户甲的课程" in a.result()["answer"] and "用户乙" not in a.result()["answer"]
    assert "用户乙的课程" in b.result()["answer"] and "用户甲" not in b.result()["answer"]


def test_sync_routes_bypass_both_query_engines(monkeypatch):
    model = MagicMock(side_effect=AssertionError("sync must not invoke graph or legacy"))
    monkeypatch.setattr(orchestrator, "run_agent", model)
    for engine in ("legacy", "langgraph"):
        monkeypatch.setenv("AGENT_ENGINE", engine)
        tools = MagicMock()
        tools.sync_schedule.return_value = {"ok":True,"state":"queued","job_id":"job-1"}
        tools.get_schedule_status.return_value = {"school_bound":True,"sync_job":{"state":"succeeded"}}
        assert "已提交" in orchestrator.handle_message("同步课表", tools)["answer"]
        assert "同步成功" in orchestrator.handle_message("同步好了吗", tools)["answer"]
    model.assert_not_called()


def test_legacy_is_default_and_unknown_engine_fails_closed(monkeypatch):
    monkeypatch.delenv("AGENT_ENGINE", raising=False)
    old = MagicMock(return_value={"answer":"legacy"})
    monkeypatch.setattr(loop, "_run", old)
    assert loop.run(make_tools(), "你好") == {"answer":"legacy"}
    old.assert_called_once()
    monkeypatch.setenv("AGENT_ENGINE", "misspelled")
    assert loop.run(make_tools(), "你好") is None
    assert old.call_count == 1


def test_no_tracing_export_and_no_persistent_checkpointer(monkeypatch):
    from contextlib import nullcontext
    tracing = MagicMock(return_value=nullcontext())
    monkeypatch.setattr(graph, "tracing_context", tracing)
    result, _, _ = replay(monkeypatch, "langgraph", "你好", [reply_message(content="在的，可以帮你查课表")])
    assert result is not None
    tracing.assert_called_once_with(enabled=False)
    runtime = graph.QueryRun(make_tools(), "你好", [])
    compiled = graph.build_graph(runtime)
    assert compiled.checkpointer is None
    assert compiled.store is None


def test_shared_execution_budget_is_not_reset_by_graph(monkeypatch):
    monkeypatch.setenv("AGENT_ENGINE", "langgraph")
    with budget.execution():
        deadline = budget._deadline.get()
        replay(monkeypatch, "langgraph", "你好", [reply_message(content="在的，可以帮你查课表")])
        assert budget._deadline.get() == deadline



def test_unconfigured_graph_does_not_load_tools_or_change_breaker(monkeypatch):
    monkeypatch.setattr(loop, "agent_config", lambda: ("", "", ""))
    build = MagicMock(side_effect=AssertionError("unconfigured runtime must not load tools"))
    monkeypatch.setattr(loop, "build_skills", build)
    monkeypatch.setenv("AGENT_ENGINE", "langgraph")
    assert loop.run(None, "你好") is None
    build.assert_not_called()
    assert llm_circuit_breaker._failure_count == 0
