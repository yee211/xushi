from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.orchestrator import handle_message, parse_intent
from app.agent.tools import AgentContext, ScheduleTools
from app.services.schedule_query import (
    ScheduleQueryError,
    materialize_courses,
    next_course,
    query_courses_by_week,
    resolve_course_name,
    select_effective_schedule,
    teaching_week,
)


def schedule(sid=1, variant="original", source=None):
    return {"id": sid, "name": "测试课表", "term": "2026-2027-1", "start_date": date(2026, 9, 7),
            "end_date": date(2027, 1, 24), "variant_type": variant, "source_schedule_id": source}

def course(cid, name, weekday, start, end, weeks=None, room="A101"):
    return {"id": cid, "name": name, "teacher": "张老师", "room": room, "weekday": weekday,
            "start_section": start, "end_section": end, "weeks": weeks if weeks is not None else [1, 2, 3]}

def test_teaching_week_and_boundaries():
    value = schedule()
    assert teaching_week(value, date(2026, 9, 7)) == 1
    assert teaching_week(value, date(2026, 9, 13)) == 1
    assert teaching_week(value, date(2026, 9, 14)) == 2
    assert teaching_week(value, date(2026, 9, 6)) is None
    assert teaching_week(value, date(2027, 1, 25)) is None

def test_adjusted_wins_and_independent_schedules_need_default():
    assert select_effective_schedule([schedule(10), schedule(11, "adjusted", 10)], date(2026, 9, 14))["id"] == 11
    with pytest.raises(ScheduleQueryError) as caught:
        select_effective_schedule([schedule(10), schedule(20)], date(2026, 9, 14))
    assert caught.value.code == "AMBIGUOUS_SCHEDULE"
    assert select_effective_schedule([schedule(10), schedule(20)], date(2026, 9, 14), 20)["id"] == 20

def test_adjustment_is_applied_before_weekday_filter():
    courses = [course(1, "高数", 1, 1, 2), course(2, "英语", 2, 5, 6)]
    changes = [{"course_id": 1, "week": 2, "weekday": 2, "start_section": 7, "end_section": 8, "room": "B202"}]
    assert materialize_courses(courses, changes, 2, 1) == []
    result = materialize_courses(courses, changes, 2, 2)
    assert [item["name"] for item in result] == ["英语", "高数"]
    assert result[1]["adjusted"] is True and result[1]["room"] == "B202"
    assert (result[1]["start_time"], result[1]["end_time"]) == ("16:00", "17:40")

def test_empty_weeks_and_cross_period_course():
    courses = [course(1, "跨午课", 1, 4, 5, []), course(2, "晚课", 1, 9, 10, [])]
    assert materialize_courses(courses, [], 25, 1, "morning")[0]["name"] == "跨午课"
    assert materialize_courses(courses, [], 25, 1, "afternoon")[0]["name"] == "跨午课"

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

def test_next_course_ongoing_then_upcoming():
    db = FakeDb([schedule()], [course(1, "高数", 1, 1, 2), course(2, "英语", 1, 3, 4)])
    tz = ZoneInfo("Asia/Shanghai")
    assert next_course(db, 1, datetime(2026, 9, 7, 9, 30, tzinfo=tz))["status"] == "ongoing"
    result = next_course(db, 1, datetime(2026, 9, 7, 10, 5, tzinfo=tz))
    assert result["status"] == "upcoming" and result["course"]["name"] == "英语"

def test_week_query_returns_requested_weekday():
    db = FakeDb([schedule()], [course(1, "英语", 3, 3, 4)])
    result = query_courses_by_week(db, 1, date(2026, 9, 8), weekday=3)
    assert result["week_start"] == "2026-09-07"
    assert len(result["days"]) == 1
    assert result["days"][0]["courses"][0]["name"] == "英语"

def test_chinese_intent_dates_and_periods():
    today = date(2026, 9, 8)
    parsed = parse_intent("下周三下午有什么课", today)
    assert parsed.name == "QUERY_DAY"
    assert parsed.target_date == date(2026, 9, 16)
    assert parsed.period == "afternoon"
    assert parse_intent("我下一节课是什么", today).name == "QUERY_NEXT"

def test_week_intent_without_specific_weekday():
    today = date(2026, 9, 8)
    parsed = parse_intent("这周有什么课", today)
    assert parsed.name == "QUERY_WEEK" and parsed.target_date == date(2026, 9, 7)
    next_week = parse_intent("下周课表", today)
    assert next_week.name == "QUERY_WEEK" and next_week.target_date == date(2026, 9, 14)
    assert parse_intent("下周三有什么课", today).name == "QUERY_DAY"

def test_find_course_intent_extracts_name():
    today = date(2026, 9, 8)
    assert parse_intent("高数什么时候上", today).course_name == "高数"
    assert parse_intent("英语课在哪上", today).course_name == "英语"
    assert parse_intent("什么时候有体育课", today).course_name == "体育"
    assert parse_intent("高数老师是谁", today).course_name == "高数"
    assert parse_intent("今天下午有什么课", today).name == "QUERY_DAY"
    assert parse_intent("今天天气怎么样", today).name == "QUERY_WEATHER"
    assert parse_intent("今天天气怎么样", today).target_date == today


def test_course_abbreviation_resolves_only_when_unique():
    catalog = [{"course_id": 1, "name": "计算机组成原理"}, {"course_id": 2, "name": "计算机网络"}]
    matched = resolve_course_name("计组", catalog)
    assert matched["status"] == "matched" and matched["course"]["course_id"] == 1
    ambiguous = resolve_course_name("计算机", catalog)
    assert ambiguous["status"] == "ambiguous" and len(ambiguous["candidates"]) == 2

def test_orchestrator_renders_facts_from_tool_result():
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    result = handle_message("今天下午有什么课", tools)
    assert result["intent"] == "QUERY_DAY"
    assert "高数" in result["answer"] and "14:00" in result["answer"]

def test_orchestrator_week_and_course_queries():
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    week = handle_message("这周有什么课", tools)
    assert week["intent"] == "QUERY_WEEK" and "高数" in week["answer"]
    found = handle_message("高数什么时候上", tools)
    assert found["intent"] == "FIND_COURSE" and "2026-09-09" in found["answer"]


def test_orchestrator_resolves_user_course_abbreviation():
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "计算机组成原理", 3, 1, 2)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    result = handle_message("计组什么时候上", tools)
    assert result["intent"] == "FIND_COURSE"
    assert "计算机组成原理" in result["answer"] and "2026-09-09" in result["answer"]


def test_orchestrator_course_absence_answers_first_then_lists_day(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "计算机网络", 3, 5, 6), course(2, "应用程序设计", 3, 7, 8),
                               course(3, "机组运行", 2, 1, 2)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    result = handle_message("明天有机组课吗", tools)
    assert result["intent"] == "QUERY_COURSE_ON_DAY"
    assert "2026-09-09（周三）没有机组运行课。当天有这 2 门课：" in result["answer"]
    assert "计算机网络" in result["answer"] and "应用程序设计" in result["answer"]


def test_orchestrator_course_presence_on_day_answers_yes(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "机组运行", 3, 5, 6), course(2, "计算机网络", 3, 1, 2)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    result = handle_message("明天有机组课吗", tools)
    assert result["intent"] == "QUERY_COURSE_ON_DAY"
    assert "2026-09-09（周三）有机组运行课：" in result["answer"] and "14:00" in result["answer"]


def test_orchestrator_unknown_course_on_day_still_answers_no(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "计算机网络", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    result = handle_message("明天有机组课吗", tools)
    assert result["intent"] == "QUERY_COURSE_ON_DAY"
    assert "没有机组课。当天有这 1 门课：" in result["answer"]


def test_orchestrator_prefers_agent_loop(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.run_agent",
                        lambda tools, message, history: {"answer": "循环回答", "skills": ["query_day_courses"],
                                                          "tool_result": {"skills": []}})
    result = handle_message("今天下午有什么课", tools)
    assert result["intent"] == "AGENT_LOOP" and result["answer"] == "循环回答"
    assert result["resolved_context"]["skills"] == ["query_day_courses"]


def test_orchestrator_weather_intent_answers_rain_yes_no(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "计算机网络", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.day_rain",
                        lambda target, period="all": {"rain": True, "peak": 80})
    monkeypatch.setattr("app.agent.orchestrator.rain_advisory",
                        lambda target_date, courses: "☔ 提醒：记得带伞。")
    result = handle_message("明天要带伞吗", tools)
    assert result["intent"] == "QUERY_WEATHER"
    assert "预报有雨" in result["answer"] and "记得带伞" in result["answer"] and "☔" in result["answer"]
    monkeypatch.setattr("app.agent.orchestrator.day_rain",
                        lambda target, period="all": {"rain": False, "peak": 10})
    result = handle_message("明天要带伞吗", tools)
    assert "没有雨" in result["answer"] and "不用带伞" in result["answer"] and "1 门课" in result["answer"]


def test_orchestrator_weather_unavailable_answers_gracefully(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.day_rain", lambda target, period="all": None)
    result = handle_message("明天会下雨吗", tools)
    assert result["intent"] == "QUERY_WEATHER" and "查不到" in result["answer"]


def test_orchestrator_appends_rain_advisory_only_for_day_queries(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 3, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 22, 0, tzinfo=tz)))
    calls = []

    def fake_advisory(target_date, courses):
        calls.append(target_date)
        return "☔ 提醒：记得带伞。"

    monkeypatch.setattr("app.agent.orchestrator.rain_advisory", fake_advisory)
    result = handle_message("明天有什么课", tools)
    assert result["answer"].endswith("☔ 提醒：记得带伞。")
    handle_message("这周有什么课", tools)
    assert calls == ["2026-09-09"]


def test_orchestrator_uses_llm_before_rules(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 3, 1, 2)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    calls = []

    def fake_extract(message, today, **kwargs):
        calls.append((message, kwargs))
        return {"name": "QUERY_DAY", "target_date": "2026-09-09", "period": "morning",
                "weekday": None, "course_name": ""}

    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", fake_extract)
    result = handle_message("帮我看看", tools, history=[object()])
    assert calls and calls[0][1]["history"]
    assert calls[0][1]["course_catalog"][0]["name"] == "高数"
    assert result["intent"] == "QUERY_DAY" and "高数" in result["answer"]


def test_orchestrator_skips_catalog_query_for_rules_only_path(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    calls = []
    original = tools.list_course_catalog

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(tools, "list_course_catalog", counting)
    result = handle_message("今天下午有什么课", tools)
    assert result["intent"] == "QUERY_DAY" and calls == []


def test_orchestrator_polishes_final_answer(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.polish_answer",
                        lambda message, answer, tool_result, history, now:
                        "明天下午 14:00 有高数课，在 A101，张老师带哦。" if "14:00" in answer else None)
    result = handle_message("今天下午有什么课", tools)
    assert result["answer"] == "明天下午 14:00 有高数课，在 A101，张老师带哦。"


def test_orchestrator_keeps_template_when_polish_unavailable(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.polish_answer", lambda *args, **kwargs: None)
    result = handle_message("今天下午有什么课", tools)
    assert "14:00–15:40（第5–6节）高数，A101，张老师" in result["answer"]


def test_orchestrator_small_talk_for_help(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: True)
    monkeypatch.setattr("app.agent.orchestrator.small_talk",
                        lambda message, history: "在的呢～可以帮你查课表，比如明天有什么课")
    result = handle_message("你好", tools)
    assert result["intent"] == "HELP" and "查课表" in result["answer"]
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: False)
    assert "你可以问我" in handle_message("你好", tools)["answer"]


def test_orchestrator_falls_back_to_rules_when_llm_unavailable(monkeypatch):
    tz = ZoneInfo("Asia/Shanghai")
    db = FakeDb([schedule()], [course(1, "高数", 2, 5, 6)])
    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=tz)))
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    result = handle_message("今天下午有什么课", tools)
    assert result["intent"] == "QUERY_DAY" and "高数" in result["answer"]
