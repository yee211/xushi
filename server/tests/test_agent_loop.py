"""工具调用主循环（agent/loop 与 skills）测试：全部 mock httpx，不发真实请求。"""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import loop  # noqa: E402
from app.agent import skills as skills_module  # noqa: E402
from app.agent.tools import AgentContext, ScheduleTools  # noqa: E402
from app.services.schedule_query import teaching_week  # noqa: E402


def schedule():
    return {"id": 1, "name": "测试课表", "term": "2026-2027-1", "start_date": date(2026, 9, 7),
            "end_date": date(2027, 1, 24), "variant_type": "original", "source_schedule_id": None}


def course(cid, name, weekday, start, end):
    return {"id": cid, "name": name, "teacher": "张老师", "room": "A101", "weekday": weekday,
            "start_section": start, "end_section": end, "weeks": [1, 2, 3]}


class FakeResult:
    def __init__(self, rows): self.rows = rows

    def fetchall(self): return self.rows


class FakeDb:
    def __init__(self, schedules, courses): self.schedules, self.courses = schedules, courses

    def execute(self, sql, params):
        if "FROM schedules" in sql:
            return FakeResult([item for item in self.schedules if teaching_week(item, params[1]) is not None])
        if "FROM courses" in sql:
            return FakeResult(self.courses)
        if "FROM course_adjustments" in sql:
            return FakeResult([])
        raise AssertionError(sql)


def make_tools(courses=None):
    db = FakeDb([schedule()], courses if courses is not None else [course(1, "高数", 3, 5, 6)])
    return ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai"))))


class FakeResponse:
    def __init__(self, payload): self._payload = payload

    def raise_for_status(self): pass

    def json(self): return self._payload


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def reply_message(content=None, tool_calls=None):
    reply = {"role": "assistant", "content": content}
    if tool_calls:
        reply["tool_calls"] = tool_calls
    return {"choices": [{"message": reply}]}


def configure(monkeypatch, responses):
    """按顺序回放 LLM 响应，并记录每次请求体供断言。"""
    monkeypatch.setenv("AGENT_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("AGENT_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    sent, remaining = [], list(responses)

    def fake_post(url, **kwargs):
        sent.append(kwargs["json"])
        return FakeResponse(remaining.pop(0))

    monkeypatch.setattr(loop.httpx, "post", fake_post)
    return sent


def test_loop_calls_skill_then_answers(monkeypatch):
    final = "明天 14:00 有高数课，在 A101，张老师带哦。"
    sent = configure(monkeypatch, [
        reply_message(tool_calls=[tool_call("c1", "query_day_courses", '{"date": "2026-09-09"}')]),
        reply_message(content=final),
    ])
    result = loop.run(make_tools(), "明天有什么课")
    assert result["answer"] == final and result["skills"] == ["query_day_courses"]
    assert sent[1]["messages"][-2]["tool_calls"][0]["function"]["name"] == "query_day_courses"
    assert "高数" in sent[1]["messages"][-1]["content"]
    assert any(item["function"]["name"] == "query_day_courses" for item in sent[0]["tools"])


def test_loop_answers_chitchat_without_skills(monkeypatch):
    configure(monkeypatch, [reply_message(content="在的～可以帮你查课表哦")])
    result = loop.run(make_tools(), "你好")
    assert result["answer"].startswith("在的") and result["skills"] == []


def test_loop_rejects_hallucinated_time(monkeypatch):
    configure(monkeypatch, [
        reply_message(tool_calls=[tool_call("c1", "query_day_courses", '{"date": "2026-09-09"}')]),
        reply_message(content="明天 18:30 有高数课。"),
    ])
    assert loop.run(make_tools(), "明天有什么课") is None


def test_loop_returns_none_on_llm_error(monkeypatch):
    import httpx as httpx_module
    monkeypatch.setenv("AGENT_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("AGENT_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MODEL", "test-model")

    def boom(**kwargs): raise httpx_module.ConnectError("network down")

    monkeypatch.setattr(loop.httpx, "post", boom)
    assert loop.run(make_tools(), "明天有什么课") is None


def test_loop_gives_up_after_max_rounds(monkeypatch):
    configure(monkeypatch, [reply_message(tool_calls=[tool_call(f"c{i}", "query_day_courses",
                                                              '{"date": "2026-09-09"}')])
                            for i in range(loop.MAX_ROUNDS + 2)])
    assert loop.run(make_tools(), "明天有什么课") is None


def test_loop_returns_none_when_unconfigured(monkeypatch):
    for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL",
                 "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert loop.run(make_tools(), "明天有什么课") is None


def test_dispatch_folds_every_failure_into_error_payload(monkeypatch):
    for name in ("WEATHER_LATITUDE", "WEATHER_LONGITUDE"):
        monkeypatch.delenv(name, raising=False)
    all_skills = skills_module.build_skills(make_tools())
    assert "未知技能" in skills_module.dispatch(all_skills, "nope", "{}")["error"]
    assert "缺少必填参数" in skills_module.dispatch(all_skills, "query_day_courses", "{}")["error"]
    assert "参数不合法" in skills_module.dispatch(all_skills, "query_day_courses", '{"date": "bad"}')["error"]
    assert skills_module.dispatch(all_skills, "query_day_courses", '不是json')["error"]
    weather = skills_module.dispatch(all_skills, "get_weather", '{"date": "2026-09-09"}')
    assert weather["rain"] is None  # 未配置坐标时天气技能如实返回不可用


def test_dispatch_reports_ambiguous_course():
    courses = [course(1, "高等数学", 3, 1, 2), course(2, "大学英语", 3, 3, 4)]
    all_skills = skills_module.build_skills(make_tools(courses))
    result = skills_module.dispatch(all_skills, "find_course", '{"name": "学"}')
    assert result["error"] == "AMBIGUOUS_COURSE"
