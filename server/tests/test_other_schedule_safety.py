"""Peer schedule safety: real renderers, graph validation and service boundaries."""
# ruff: noqa: F811 -- imported pytest fixtures are referenced by test parameters
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from app.agent import graph, loop, orchestrator
from app.agent.completion import finalize
from app.agent.other_reply import render_other_facts
from app.agent.sync import status_requested
from app.agent.tools import AgentContext, ScheduleTools
from app.services import academic_others as service
from tests.test_academic_others import _sample_snapshot, db  # noqa: F401
from tests.test_agent_graph import isolated_engine  # noqa: F401
from tests.test_agent_loop import make_tools, reply_message, tool_call
from tests.test_agent_sync_multiturn import flow  # noqa: F401


def fact(skill, result, **args):
    return {"skill": skill, "result": result, "arguments": json.dumps(args)}


def day(name="数据结构", hour="14:00"):
    return {"date": "2026-09-09", "period": "afternoon", "courses": [
        {"name": name, "start_time": hour, "end_time": "15:40", "teacher": "张", "room": "A101"}]}


def group_fact():
    return fact("check_group_availability", {
        "date": "2026-09-09", "period": "afternoon", "common_free_slots": [],
        "participants": [
            {"role": "me", "display_name": "我", "completely_free": False, "course_count": 1,
             "courses": [], "free_slots": [{"start_time": "14:00", "end_time": "15:40"}]},
            {"role": "other", "display_name": "李四", "completely_free": False, "course_count": 1,
             "courses": [], "free_slots": [{"start_time": "16:00", "end_time": "17:40"}]},
        ]})


@pytest.mark.parametrize("answer", ["明天下午你们都有空。", "李四明天下午没有课。", "你们的共同空闲时间是 14:00–15:40。"])
def test_false_group_conclusions_are_rejected(answer):
    assert not loop._facts_grounded(answer, [group_fact()], "明天下午我和室友都有空吗")


def test_group_answer_is_rendered_from_facts(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "明天下午我和室友都有空吗", [])
    result = runtime.validate({"facts": [group_fact()], "rounds": 2, "messages": [],
                               "reply": reply_message(content='{"status":"completed","answer":"你们都有空","task_id":null}')["choices"][0]["message"]})
    assert "没有共同空闲" in result["answer"]["answer"]
    assert "李四：所选时段有1节课" in result["answer"]["answer"]


@pytest.mark.parametrize("skill", ["query_day_courses", "query_other_day_courses"])
def test_group_query_requires_group_tool(isolated_engine, skill):
    runtime = graph.QueryRun(make_tools(), "明天下午我和室友都有空吗", [])
    result = runtime.validate({"facts": [fact(skill, day())], "rounds": 2, "messages": [],
                               "reply": {"content": '{"status":"completed","answer":"都有空","task_id":null}'}})
    assert result["route"] == "model"
    assert runtime.saved_answer([fact(skill, day())]) is None


def test_mixed_course_reply_preserves_both_people_and_recovers(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "明天我和室友有什么课", [])
    facts = [fact("query_day_courses", day("高等数学", "08:20")),
             fact("query_other_day_courses", {**day(), "person": {"display_name": "室友（李四）"}})]
    reply = runtime.saved_answer(facts)
    assert "高等数学" in reply["answer"] and "数据结构" in reply["answer"]
    assert "室友（李四）" in reply["answer"]
    assert runtime.saved_answer(facts[:1]) is None
    assert graph.QueryRun(make_tools(), "室友明天有什么课", []).saved_answer(facts[1:])


@pytest.mark.parametrize("code,message", [
    ("NO_OTHER_SCHEDULES", "你还没有保存任何他人课表，可以去添加。"),
    ("PERSON_NOT_FOUND", "在已保存的他人课表中没有找到王五。"),
])
def test_actionable_errors_survive_without_model_rephrasing(isolated_engine, code, message):
    facts = [fact("query_other_day_courses", {"error": code, "message": message})]
    assert loop._facts_grounded(message, facts, "室友明天有什么课")
    reply = graph.QueryRun(make_tools(), "室友明天有什么课", []).saved_answer(facts)
    assert reply["answer"] == message
    assert reply["_completion_status"] == "needs_input"


def test_date_clarification_still_allowed_for_other_person(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "室友有什么课", [])
    reply = runtime.validate({"facts": [], "rounds": 1, "messages": [],
                              "reply": {"content": '{"status":"needs_input","answer":"请提供要查询的日期？","task_id":null}'}})
    assert reply["answer"]["_completion_status"] == "needs_input"


def test_class_only_question_never_uses_personal_fallback(monkeypatch):
    tools = make_tools()
    tools.list_other_people = Mock(return_value={"people": [{"class_name": "软件2401"}]})
    tools.get_courses_by_date = Mock(side_effect=AssertionError("personal query"))
    result = orchestrator._fallback_reply("软件2401明天有什么课", tools, allow_llm=False)
    assert result["error"]["code"] == "other_query_unavailable"


def test_network_queries_do_not_hold_database_connections(db, monkeypatch):
    active = 0
    @contextmanager
    def factory():
        nonlocal active
        active += 1
        try:
            yield db
        finally:
            active -= 1
    student = {"id": "student-a", "default_term": "2026-2027-1"}
    def search(keyword):
        assert active == 0
        return {"students": [student]}
    def query(*args):
        assert active == 0
        return _sample_snapshot("李四", "软件2401", [])
    monkeypatch.setattr(service.academic, "search_keyword", search)
    monkeypatch.setattr(service.academic, "get_schedule", query)
    tools = ScheduleTools(factory, AgentContext(1, datetime.now(UTC)))
    assert tools.add_other_schedule("李四")["ok"]
    assert active == 0


def test_default_term_and_omitted_remark(db, monkeypatch):
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: _sample_snapshot("李四", "软件2401", []))
    service.save(1, "student-a", "2026-2027-1", "室友")
    service.save(1, "student-a", "2026-2027-1")
    assert db.rows[1, "student-a"]["remark"] == "室友"
    service.save(1, "student-a", "2026-2027-1", "")
    assert db.rows[1, "student-a"]["remark"] == ""
    assert service._default_term_for_user(None, 1, {"default_term": "2026-2027-1"}) == "2026-2027-1"
    today = datetime.now(service.ZoneInfo("Asia/Shanghai"))
    expected_year = today.year if today.month >= 8 else today.year - 1
    assert service._default_term_for_user(None, 1, {}).startswith(str(expected_year))


def test_business_failure_cannot_be_marked_completed():
    result = finalize({"answer": "已添加", "_completion_status": "completed", "tool_result": {"skills": [fact("add_other_schedule", {
        "ok": False, "status": "not_found", "message": "没有找到同学", "error": "STUDENT_NOT_FOUND"})]}})
    assert result["status"] == "failed" and result["answer"] == "没有找到同学"


def test_input_required_status_overrides_incorrect_model_completion():
    result = finalize({"answer": "已添加", "_completion_status": "completed", "tool_result": {"skills": [fact("add_other_schedule", {
        "ok": False, "status": "needs_input", "message": "请提供姓名", "error": "ADD_NEEDS_INPUT"})]}})
    assert result["status"] == "needs_input" and result["answer"] == "请提供姓名"


@pytest.mark.parametrize("text", ["保存的课表更新了吗", "我保存的课表是最新的吗"])
def test_saved_schedule_status_remains_a_status_question(text):
    assert status_requested(text)
    assert not status_requested("帮我保存李四的课表")


def test_favorites_cap_still_allows_updates(db, monkeypatch):
    monkeypatch.setattr(service, "MAX_SAVED_PEOPLE", 1)
    service.save(1, "student-a", "2026-2027-1")
    service.save(1, "student-a", "2026-2027-1", "新备注")
    with pytest.raises(service.academic.AcademicError) as caught:
        service.save(1, "student-b", "2026-2027-1")
    assert caught.value.code == "saved_people_limit"


def test_rate_limit_stops_upstream_query(monkeypatch):
    monkeypatch.setattr(service.query_limiter, "hit", lambda key: (False, 10))
    upstream = Mock()
    monkeypatch.setattr(service.academic, "get_schedule", upstream)
    with pytest.raises(service.academic.AcademicError) as caught:
        service.query("student-a", "2026-2027-1", user_id=1)
    assert caught.value.code == "too_many_queries"
    upstream.assert_not_called()


def test_people_choices_are_persisted_and_resolved_without_model_ids(flow, monkeypatch):
    db, redis, responses, requests, client, finish, say = flow
    students = [{"id": f"student-{i}", "name": "张三", "class_name": f"软件240{i}",
                 "student_number_display": f"2024000{i}", "default_term": "2026-2027-1"} for i in (1, 2)]
    monkeypatch.setattr(service.query_limiter, "hit", lambda key: (True, 0))
    search = Mock(return_value={"students": students})
    monkeypatch.setattr(service.academic, "search_keyword", search)
    monkeypatch.setattr(service.academic, "student_context", lambda sid: next(s for s in students if s["id"] == sid))
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: _sample_snapshot("张三", "软件2402", []))
    saved = []
    def upsert(conn, uid, sid, term, remark, snapshot):
        saved.append((sid, remark))
        return dict(student_id=sid, term=term, remark=remark, snapshot=snapshot)
    monkeypatch.setattr(service, "_upsert_row", upsert)
    responses.extend([
        reply_message(tool_calls=[tool_call("add", "add_other_schedule", '{"keyword":"张三","remark":"室友"}')]),
        reply_message(content='{"status":"needs_input","answer":"请选择班级？","task_id":null}'),
    ])
    assert "软件2402" in say("帮我添加张三的课表，备注室友")
    call_count = len(requests)
    assert "已添加" in say("第2位")
    assert saved == [("student-2", "室友")]
    assert len(requests) == call_count
    search.assert_called_once()


def test_renderer_never_invents_common_slots():
    assert "没有共同空闲" in render_other_facts([group_fact()], date(2026, 9, 8))


@pytest.mark.parametrize("change", ["delete", "remark", "term"])
def test_refresh_cannot_resurrect_or_overwrite_concurrent_changes(db, monkeypatch, change):
    service.save(1, "student-a", "2026-2027-1", "室友")
    def upstream(*args):
        if change == "delete":
            service.remove(1, "student-a")
        else:
            db.rows[1, "student-a"][change] = "新内容"
            db.rows[1, "student-a"]["updated_at"] += 1
        return _sample_snapshot("李四", "软件2401", [])
    monkeypatch.setattr(service.academic, "get_schedule", upstream)
    with pytest.raises(service.academic.AcademicError) as caught:
        service.refresh_saved(1, "student-a")
    assert caught.value.code == "saved_person_changed"
    if change == "delete":
        assert (1, "student-a") not in db.rows
    else:
        assert db.rows[1, "student-a"][change] == "新内容"


def test_refresh_preserves_remark(db, monkeypatch):
    service.save(1, "student-a", "2026-2027-1", "室友")
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: _sample_snapshot("李四", "软件2401", []))
    assert service.refresh_saved(1, "student-a")["remark"] == "室友"


@pytest.mark.parametrize("query,expected", [
    ("软件1班张三", ["软件1班", "张三"]),
    ("软件2401张三", ["软件2401", "张三"]),
    ("软件1班 张三", ["软件1班", "张三"]),
    ("2024012345", ["2024012345"]),
])
def test_directory_search_splits_composite_terms(query, expected):
    from app.services.academic_directory import _search_tokens
    assert _search_tokens(query) == expected


def test_date_followup_preserves_other_person_scope(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "明天呢", [{"role": "user", "content": "今天我和室友有什么课"}])
    assert not runtime.scope_complete([fact("query_day_courses", day())])
