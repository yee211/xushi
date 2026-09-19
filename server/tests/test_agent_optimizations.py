"""Tests for Agent pipeline optimizations: Circuit Breaker, connection pooling, and parallel tools."""
import json
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.agent.circuit_breaker import CircuitBreaker, CircuitState, llm_circuit_breaker
from app.agent.http_client import close_llm_client, get_llm_client
from app.agent.loop import _extract_context_entities
from app.agent.orchestrator import handle_message
from app.agent.tools import AgentContext


def test_circuit_breaker_flow():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # 1 failure: still closed
    cb.record_failure(RuntimeError("timeout 1"))
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # 2 failures: threshold reached -> OPEN
    cb.record_failure(RuntimeError("timeout 2"))
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False

    # Wait for recovery timeout -> transitions to HALF_OPEN on allow_request
    time.sleep(0.12)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    # In HALF_OPEN, second concurrent request is rejected
    assert cb.allow_request() is False

    # Probe succeeds -> transitions to CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_probe_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
    cb.record_failure(RuntimeError("fail"))
    assert cb.state == CircuitState.OPEN

    time.sleep(0.06)
    assert cb.allow_request() is True  # triggers HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN

    # Probe fails -> immediately re-opens
    cb.record_failure(RuntimeError("probe failed"))
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_handle_message_bypasses_llm_when_circuit_open(monkeypatch):
    run_called = []
    fallback_llm_calls = []

    def fake_run(tools, message, history=None):
        run_called.append(True)
        return {"answer": "llm answer", "skills": [], "tool_result": {}}

    monkeypatch.setattr("app.agent.orchestrator.run_agent", fake_run)
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.extract_intent",
                        lambda *args, **kwargs: fallback_llm_calls.append("intent"))
    monkeypatch.setattr("app.agent.orchestrator.polish_answer",
                        lambda *args, **kwargs: fallback_llm_calls.append("polish"))
    monkeypatch.setattr("app.agent.orchestrator.small_talk",
                        lambda *args, **kwargs: fallback_llm_calls.append("small_talk"))

    llm_circuit_breaker.reset()
    try:
        # Trip the circuit breaker
        llm_circuit_breaker.record_failure("error 1")
        llm_circuit_breaker.record_failure("error 2")
        llm_circuit_breaker.record_failure("error 3")
        assert llm_circuit_breaker.allow_request() is False

        # Create a mock ScheduleTools
        tools = MagicMock()
        tools.context = AgentContext(user_id=1, now=datetime(2026, 9, 14, 10, 0, tzinfo=UTC), timezone="Asia/Shanghai")
        tools.list_course_catalog.return_value = []
        tools.get_courses_by_date.return_value = {"date": "2026-09-14", "weekday": 1, "courses": []}

        # Should immediately return deterministic answer without calling run_agent
        result = handle_message("今天下午有什么课", tools)
        assert len(run_called) == 0, "熔断打开时绝不得调用 run_agent"
        assert fallback_llm_calls == [], "熔断打开时兜底链路也不得调用任何 LLM"
        assert "2026-09-14" in result["answer"]
    finally:
        llm_circuit_breaker.reset()


def test_extract_context_entities():
    facts = [
        {"skill": "query_day_courses", "arguments": json.dumps({"date": "2026-09-15", "period": "morning"}), "result": {}},
        {"skill": "find_course", "arguments": json.dumps({"name": "高等数学"}), "result": {}},
    ]
    resolved = _extract_context_entities(facts)
    assert resolved["intent"] == "AGENT_LOOP"
    assert resolved["target_date"] == "2026-09-15"
    assert resolved["period"] == "morning"
    assert resolved["course_name"] == "高等数学"
    assert resolved["skills"] == ["query_day_courses", "find_course"]


def test_parallel_tool_calls_in_loop(monkeypatch):
    from app.agent import loop as loop_module

    # Mock agent_config to return dummy values
    monkeypatch.setattr(loop_module, "agent_config", lambda: ("https://api.example.com", "key", "model"))

    # Mock LLM response with 2 tool calls
    calls = [
        {"id": "call_1", "function": {"name": "query_day_courses", "arguments": json.dumps({"date": "2026-09-14"})}},
        {"id": "call_2", "function": {"name": "get_weather", "arguments": json.dumps({"date": "2026-09-14"})}},
    ]
    round_count = 0

    class FakeClient:
        def post(self, url, **kwargs):
            nonlocal round_count
            round_count += 1
            if round_count == 1:
                return MagicMock(
                    raise_for_status=lambda: None,
                    json=lambda: {"choices": [{"message": {"content": "", "tool_calls": calls}}]}
                )
            # Second turn: return final response
            return MagicMock(
                raise_for_status=lambda: None,
                json=lambda: {"choices": [{"message": {"content": "今天有课，没有雨。"}}]}
            )

    monkeypatch.setattr(loop_module, "get_llm_client", lambda: FakeClient())

    # Mock dispatch with delay to verify parallel execution
    delays = []

    def fake_dispatch(skills, name, arguments):
        time.sleep(0.06)
        delays.append(name)
        return {"data": name}

    monkeypatch.setattr(loop_module, "dispatch", fake_dispatch)
    monkeypatch.setattr(loop_module, "_grounded", lambda content, ctx: True)

    tools = MagicMock()
    tools.context = AgentContext(user_id=1, now=datetime(2026, 9, 14, 10, 0, tzinfo=UTC), timezone="Asia/Shanghai")

    t_start = time.monotonic()
    result = loop_module.run(tools, "今天有什么课，会下雨吗")
    total_time = time.monotonic() - t_start

    assert result is not None
    assert result["answer"] == "今天有课，没有雨。"
    assert len(delays) == 2
    # 2 calls of 0.06s in parallel should finish in significantly less than 0.12s
    assert total_time < 0.11
    assert result["resolved_context"]["target_date"] == "2026-09-14"


def test_http_client_pooling():
    c1 = get_llm_client()
    c2 = get_llm_client()
    assert c1 is c2
    close_llm_client()
    c3 = get_llm_client()
    assert c3 is not c1
    close_llm_client()


def test_half_open_probe_reopens_on_ungrounded_response(monkeypatch):
    from app.agent import loop as loop_module

    monkeypatch.setattr(loop_module, "agent_config", lambda: ("https://api.example.com", "key", "model"))

    class FakeClient:
        def post(self, url, **kwargs):
            return MagicMock(
                raise_for_status=lambda: None,
                json=lambda: {"choices": [{"message": {"content": "编造的回答"}}]},
            )

    monkeypatch.setattr(loop_module, "get_llm_client", lambda: FakeClient())
    monkeypatch.setattr(loop_module, "_grounded", lambda content, ctx: False)

    tools = MagicMock()
    tools.context = AgentContext(user_id=1, now=datetime(2026, 9, 14, 10, 0, tzinfo=UTC),
                                 timezone="Asia/Shanghai")

    llm_circuit_breaker.reset()
    try:
        for index in range(llm_circuit_breaker.failure_threshold):
            llm_circuit_breaker.record_failure(f"failure {index}")
        # Make the recovery window elapse without sleeping.
        llm_circuit_breaker._last_state_change -= llm_circuit_breaker.recovery_timeout
        assert llm_circuit_breaker.allow_request() is True
        assert llm_circuit_breaker.state == CircuitState.HALF_OPEN

        assert loop_module.run(tools, "今天有什么课") is None
        assert llm_circuit_breaker.state == CircuitState.OPEN
    finally:
        llm_circuit_breaker.reset()
