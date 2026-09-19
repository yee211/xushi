"""回答润色层（polish_ai）测试：全部 mock httpx，验证接地校验与降级行为。"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import polish_ai  # noqa: E402

NOW = datetime(2026, 9, 8, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeResponse:
    def __init__(self, content): self._content = content

    def raise_for_status(self): pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def configure(monkeypatch, content, raises=None):
    monkeypatch.setenv("AGENT_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("AGENT_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MODEL", "test-model")

    def fake_post(url, **kwargs):
        if raises:
            raise raises("network down")
        return FakeResponse(content)

    monkeypatch.setattr(polish_ai.httpx, "post", fake_post)


ANSWER = "2026-09-09（周三）有 1 门课：\n1. 14:00–15:40（第5–6节）高数，A101，张老师"
FACTS = {"date": "2026-09-09", "courses": [
    {"name": "高数", "start_time": "14:00", "end_time": "15:40", "room": "A101", "teacher": "张老师"}]}


def test_polish_disabled_without_config(monkeypatch):
    for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL",
                 "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) is None
    assert polish_ai.small_talk("你好") is None


def test_polish_accepts_grounded_rewrite(monkeypatch):
    rewrite = "明天周三下午 14:00–15:40 有高数课，在 A101，是张老师的课～"
    configure(monkeypatch, rewrite)
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) == rewrite


def test_polish_rejects_fabricated_time(monkeypatch):
    configure(monkeypatch, "明天周三下午 16:20–18:00 有高数课，在 A101，张老师。")
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) is None


def test_polish_rejects_dropped_times_in_listing(monkeypatch):
    configure(monkeypatch, "明天周三下午有一节高数课，张老师上，别迟到啦。")
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) is None


def test_polish_rejects_lost_negative(monkeypatch):
    negative = "2026-09-09（周三）没有机组课。当天有这 1 门课：\n1. 14:00–15:40（第5–6节）计算机网络，A101，张老师"
    configure(monkeypatch, "明天周三下午 14:00 有计算机网络课。")
    assert polish_ai.polish_answer("明天有机组课吗", negative, FACTS, now=NOW) is None


def test_polish_rejects_invented_course_without_facts(monkeypatch):
    configure(monkeypatch, "明天周三下午有体育课，去田径场哦。")
    assert polish_ai.polish_answer("明天有什么课", "2026-09-09（周三）没有课。", {"courses": []},
                                   now=NOW) is None


def test_polish_falls_back_on_llm_error(monkeypatch):
    import httpx as httpx_module
    configure(monkeypatch, "", raises=httpx_module.ConnectError)
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) is None
    configure(monkeypatch, "不是正文而是说明")
    assert polish_ai.polish_answer("明天有什么课", ANSWER, FACTS, now=NOW) is None


def test_polish_must_keep_umbrella_advisory(monkeypatch):
    weather_answer = ANSWER + "\n☔ 提醒：2026-09-09 14:00–15:40《高数》时段降雨概率 80%，记得带伞。"
    configure(monkeypatch, "明天周三下午 14:00–15:40 高数课，在 A101，张老师的。")
    assert polish_ai.polish_answer("明天有什么课", weather_answer, FACTS, now=NOW) is None
    configure(monkeypatch, "明天周三 14:00–15:40 有高数课，在 A101，张老师上；有雨记得带伞哦～")
    assert "带伞" in polish_ai.polish_answer("明天有什么课", weather_answer, FACTS, now=NOW)


def test_small_talk_returns_short_reply(monkeypatch):
    configure(monkeypatch, "在的呢～可以帮你查课表，比如明天有什么课、这周安排")
    assert "查课表" in polish_ai.small_talk("你好", history=[])
    configure(monkeypatch, "这是一段超长回复" * 60)
    assert polish_ai.small_talk("你好") is None
