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
