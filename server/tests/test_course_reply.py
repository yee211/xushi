import pytest
from pydantic import ValidationError

from app.agent import loop
from app.agent.course_reply import CourseComment, CourseRow, DayCourses, render_day
from tests.test_agent_loop import configure, make_tools, reply_message, tool_call


def test_course_fields_and_comment_are_validated():
    with pytest.raises(ValidationError):
        CourseRow(name="高数", start_time="25:00", end_time="26:00")
    with pytest.raises(ValidationError):
        CourseRow(name="高数", start_time="10:00", end_time="08:00")
    with pytest.raises(ValidationError):
        CourseComment.model_validate({"closing":"提醒", "courses":[]})
    with pytest.raises(ValidationError):
        CourseComment(closing="第一行\n第二行")


def test_multi_course_sorting_and_missing_fields():
    from datetime import date
    day = DayCourses.model_validate({"date":"2026-10-15", "courses":[
        {"name":"下午课", "start_time":"14:00", "end_time":"15:40"},
        {"name":"开源软件开发", "start_time":"08:20", "end_time":"10:00", "teacher":"张宸", "room":"7-南508"}]})
    result = render_day(day, date(2026,10,14), "早点睡吧")
    assert result.startswith("明天（10月15日，周四）有2节课：")
    assert result.index("08:20") < result.index("14:00")
    assert "• 08:20–10:00 开源软件开发，张宸，7-南508" in result
    assert "• 14:00–15:40 下午课" in result
    assert result.endswith("\n\n早点睡吧")


@pytest.mark.parametrize(("content", "closing"), [
    ('{"closing":"早点休息吧"}', "早点休息吧"),
    ('{"closing":"刚才同步失败了"}', ""),
    ('{"closing":"明天18:00上课"}', ""),
    ('{"closing":"提醒", "courses":[]}', ""),
    ('高数14:00–15:40，在A101', ""),
])
def test_structured_reply_keeps_tool_list_even_if_model_format_is_wrong(monkeypatch, content, closing):
    sent = configure(monkeypatch, [
        reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content=content)])
    result = loop.run(make_tools(), "明天啥课")
    assert "• 14:00–15:40 高数，张老师，A101" in result["answer"]
    assert sent[1]["response_format"] == {"type":"json_object"}
    assert sent[1]["tool_choice"] == "none"
    if closing:
        assert result["answer"].endswith("\n\n"+closing)
    else:
        assert "同步失败" not in result["answer"] and "18:00" not in result["answer"]


@pytest.mark.parametrize("failure", ["timeout", "truncated", "queue_timeout"])
def test_model_failure_after_query_keeps_complete_facts(monkeypatch, failure):
    import httpx

    from tests.test_agent_loop import FakeResponse

    tools = make_tools()
    query = tools.get_courses_by_date
    calls = []
    def counted(*args, **kwargs):
        calls.append(args)
        return query(*args, **kwargs)
    monkeypatch.setattr(tools, "get_courses_by_date", counted)
    configure(monkeypatch, [])
    posts = []
    def post(url, **kwargs):
        posts.append(kwargs)
        if len(posts) == 1:
            return FakeResponse(reply_message(tool_calls=[tool_call("day", "query_day_courses", '{"date":"2026-09-09"}')]))
        if failure == "truncated":
            return FakeResponse({"choices":[{"finish_reason":"length", "message":{"content":"partial"}}]})
        raise httpx.TimeoutException("model unavailable")
    monkeypatch.setattr(loop, "_post_llm", post)
    if failure == "queue_timeout":
        checks = [0]
        def remaining():
            checks[0] += 1
            if checks[0] >= 3:
                raise httpx.TimeoutException("budget exhausted")
            return 10
        monkeypatch.setattr(loop, "remaining", remaining)
    result = loop.run(tools, "明天有什么课")
    assert "• 14:00–15:40 高数，张老师，A101" in result["answer"]
    assert len(calls) == 1


def test_week_and_multiple_days_share_layout():
    from datetime import date

    from app.agent.course_reply import course_facts, render_courses

    days = [
        {"date":"2026-10-15","courses":[{"name":"高数","start_time":"08:20","end_time":"10:00","teacher":"张华","room":"A101"}]},
        {"date":"2026-10-16","courses":[]}]
    weekly_days = [{"date": f"2026-10-{n}", "courses": []} for n in range(12, 19)]
    weekly_days[3] = days[0]
    weekly = [{"skill":"query_week_courses","result":{"week_start":"2026-10-12","week_end":"2026-10-18","days":weekly_days}}]
    text = render_courses(course_facts(weekly,"这周有什么课"),date(2026,10,14))
    assert "• 08:20–10:00 高数，张华，A101" in text
    multi = [{"skill":"query_day_courses","arguments":"{}","result":day} for day in days]
    text = render_courses(course_facts(multi,"明天和后天有什么课"),date(2026,10,14))
    assert "后天（10月16日，周五）没有课" in text
    assert course_facts(multi[:1],"明天和后天有什么课") is None
    assert course_facts(multi[:1],"明天有什么课，教室在哪") is not None
    assert course_facts(multi[:1],"教室在哪") is None
    assert course_facts(multi + [{"skill":"query_day_courses","result":{"error":"unavailable"}}],"明天有什么课") is None


def test_partial_week_is_not_presented_as_complete():
    from app.agent.course_reply import course_facts

    partial = [{"skill":"query_week_courses", "result":{"week_start":"2026-10-12",
        "week_end":"2026-10-18", "days":[{"date":"2026-10-12", "courses":[]}]}}]
    assert course_facts(partial, "这周有什么课") is None
    assert course_facts([{"skill":"query_day_courses", "arguments":"{}",
        "result":{"date":"2026-10-14", "courses":[]}}], "今天和明天有什么课") is None
