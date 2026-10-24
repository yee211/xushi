"""agent/telemetry 单测：turn 统计、token 累计、agent_turn 日志与 Redis 降级去抖。"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import conversation, orchestrator, telemetry  # noqa: E402
from app.agent.tools import AgentContext, ScheduleTools  # noqa: E402
from tests.test_agent_loop import FakeDb, course, schedule  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry._stats.set(None)
    yield
    telemetry._stats.set(None)


class FakeUsageResponse:
    def json(self):
        return {"usage": {"prompt_tokens": 120, "completion_tokens": 30,
                          "prompt_tokens_details": {"cached_tokens": 64}}}


def test_record_llm_call_accumulates_usage_and_tolerates_bad_payloads():
    telemetry.start_turn()
    telemetry.record_llm_call(FakeUsageResponse())
    telemetry.record_llm_call(object())  # 非 JSON 响应只计数、不抛错
    stats = telemetry.active()
    assert stats.llm_calls == 2
    assert stats.prompt_tokens == 120 and stats.completion_tokens == 30
    assert stats.cached_tokens == 64


def test_record_llm_call_ignores_calls_outside_turn():
    telemetry.record_llm_call(FakeUsageResponse())
    assert telemetry.active() is None


def test_agent_turn_log_covers_fallback_path(monkeypatch, caplog):
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(orchestrator, "rain_advisory", lambda *a, **k: None)
    db = FakeDb([schedule()], [course(1, "高数", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0,
                                                                tzinfo=ZoneInfo("Asia/Shanghai"))))
    with caplog.at_level("INFO", logger="classschedule"):
        result = orchestrator.handle_message("明天有什么课", tools)
    turns = [json.loads(record.getMessage()) for record in caplog.records
             if record.name == "classschedule" and record.getMessage().startswith('{"event"')
             and json.loads(record.getMessage()).get("event") == "agent_turn"]
    assert len(turns) == 1
    assert turns[0]["path"] == "fallback" and turns[0]["outcome"] == "ok"
    assert turns[0]["llm_calls"] == 0 and "duration_ms" in turns[0] and "breaker" in turns[0]
    assert "高数" in result["answer"]


def test_agent_turn_metrics_enqueued_for_admin_panel(monkeypatch):
    from app.services import agent_metrics

    captured = []
    monkeypatch.setattr(agent_metrics, "enqueue", captured.append)
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(orchestrator, "rain_advisory", lambda *a, **k: None)
    db = FakeDb([schedule()], [course(1, "高数", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0,
                                                                tzinfo=ZoneInfo("Asia/Shanghai"))))
    orchestrator.handle_message("明天有什么课", tools)
    assert len(captured) == 1
    turn = captured[0]
    assert turn["path"] == "fallback" and turn["outcome"] == "ok"
    assert {"rounds", "llm_calls", "prompt_tokens", "completion_tokens",
            "cached_tokens", "duration_ms", "breaker"} <= set(turn)


def test_redis_degraded_warning_is_debounced(caplog):
    conversation._redis_degraded = False
    try:
        with caplog.at_level("INFO", logger="agent.conversation"):
            conversation._note_redis_failure("load_history")
            conversation._note_redis_failure("append_turn")
            warnings = [r for r in caplog.records if "Agent Redis unavailable" in r.getMessage()]
            assert len(warnings) == 1
            conversation._note_redis_recovery()
            conversation._note_redis_failure("clarification.save")
            warnings = [r for r in caplog.records if "Agent Redis unavailable" in r.getMessage()]
            assert len(warnings) == 2
    finally:
        conversation._redis_degraded = False
