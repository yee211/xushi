"""Agent 入口每日限额与超长消息截断的行为回归。"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import orchestrator, service  # noqa: E402
from app.rate_limit import agent_daily_limiter  # noqa: E402
from tests.fakes import FakeAgentDb  # noqa: E402


def _reply(message):
    db = FakeAgentDb(identity_user_id=1)
    return service.build_agent_reply(lambda: db, message, "weixin_ilink", "sender",
                                     datetime(2026, 10, 14, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")))


def test_daily_limit_exhausted_returns_quota_message(monkeypatch):
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(agent_daily_limiter, "hit", lambda key: (False, 3600))
    assert _reply("今天有什么课") == "今天的问题额度用完了，先歇一歇，明天再来找我吧。"


def test_daily_limit_allows_normal_query(monkeypatch):
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(agent_daily_limiter, "hit", lambda key: (True, 0))
    reply = _reply("今天有什么课")
    assert "额度" not in reply


def test_overlong_message_is_truncated_with_marker(monkeypatch):
    monkeypatch.setattr(agent_daily_limiter, "hit", lambda key: (True, 0))
    captured = {}

    def fake_handle(message, tools, history=None):
        captured["message"] = message
        return {"intent": "HELP", "answer": "ok"}

    monkeypatch.setattr(service, "handle_message", fake_handle)
    assert _reply("今天有什么课" + "啦" * 600) == "ok"
    assert captured["message"].endswith("（消息过长，已截断）")
    assert len(captured["message"]) <= 500 + len("（消息过长，已截断）")
