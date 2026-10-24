"""Peer schedule safety: real renderers, graph validation and service boundaries."""
# ruff: noqa: F811 -- imported pytest fixtures are referenced by test parameters
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from app.agent import clarification, graph, loop, orchestrator
from app.agent.completion import finalize
from app.agent.other_reply import render_other_facts
from app.agent.skills import build_skills, dispatch
from app.agent.sync import status_requested
from app.agent.tools import AgentContext, ScheduleTools
from app.services import academic_others as service
from tests.test_academic_others import Db as OthersDb
from tests.test_academic_others import _sample_snapshot, db  # noqa: F401
from tests.test_agent_graph import isolated_engine, replay  # noqa: F401
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


def test_we_self_query_stays_personal(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "我们今天有什么课", [])
    assert not runtime.other_scope()
    assert runtime.scope_complete([fact("query_day_courses", day())])
    reply = runtime.saved_answer([fact("query_day_courses", day())])
    assert reply and "数据结构" in reply["answer"]


def test_we_group_query_requires_saved_people(isolated_engine):
    tools = make_tools()
    tools.list_other_people = Mock(return_value={"people": [{"name": "李四", "remark": "室友"}]})
    runtime = graph.QueryRun(tools, "我们都有空吗", [])
    assert runtime.other_scope()
    assert not runtime.scope_complete([fact("query_day_courses", day())])
    assert not graph.QueryRun(make_tools(), "我们都有空吗", []).other_scope()


def test_we_self_query_survives_deterministic_fallback():
    tools = make_tools()
    tools.list_other_people = Mock(return_value={"people": []})
    result = orchestrator._fallback_reply("我们今天有课吗", tools, allow_llm=False)
    assert not result.get("error")
    assert "2026-09-08" in result["answer"]


def _saved_row(sid, name, remark=""):
    return dict(student_id=sid, term="2026-2027-1", remark=remark,
                snapshot=_sample_snapshot(name, "软件2401", []), updated_at=1)


def _others_tools(rows):
    fake = OthersDb()
    fake.rows.update(rows)
    return fake, ScheduleTools(fake, AgentContext(1, datetime(2026, 9, 8, 13, 0, tzinfo=UTC)))


def test_remove_and_clear_skills_dispatch_end_to_end():
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三", "室友"),
                                 (1, "sid-b"): _saved_row("sid-b", "李四")})
    skills = build_skills(tools)
    assert {"remove_other_schedule", "clear_other_schedules"} <= {s.name for s in skills}

    removed = dispatch(skills, "remove_other_schedule", '{"person": "室友"}')
    assert removed["ok"] is True and removed["removed"]["name"] == "张三"
    assert (1, "sid-a") not in fake.rows and (1, "sid-b") in fake.rows

    missing = dispatch(skills, "remove_other_schedule", '{"person": "王五"}')
    assert missing["error"] == "PERSON_NOT_FOUND" and missing["candidates"]

    first = dispatch(skills, "clear_other_schedules", "{}")
    assert first["ok"] is False and first["error"] == "CLEAR_NEEDS_CONFIRM" and first["count"] == 1
    assert len(fake.rows) == 1  # 未确认绝不删除
    second = dispatch(skills, "clear_other_schedules", '{"confirm": true, "expected_count": 1}')
    assert second["error"] == "CLEAR_NEEDS_CONFIRM" and len(fake.rows) == 1
    tools.clear_student_ids = first["student_ids"]
    second = dispatch(skills, "clear_other_schedules", '{"confirm": true, "expected_count": 1}')
    assert second["ok"] is True and fake.rows == {}


def test_finalize_maps_removal_results():
    cleared = finalize({"intent": "AGENT_LOOP", "answer": "", "tool_result": {"skills": [
        fact("clear_other_schedules", {"ok": False, "error": "CLEAR_NEEDS_CONFIRM", "status": "needs_input",
                                       "count": 2, "people": ["张三", "李四"], "message": "将清空全部 2 位同学的课表，确认清空请回复“确认”。"})]}})
    assert cleared["status"] == "needs_input" and "确认" in cleared["answer"]

    removed = finalize({"intent": "AGENT_LOOP", "answer": "已移除室友（张三）的课表。",
                        "tool_result": {"skills": [
                            fact("remove_other_schedule", {"ok": True, "status": "removed", "removed": {},
                                                           "remaining": [], "message": "已移除 室友（张三）的课表。"})]}})
    assert removed["status"] == "completed"

    not_found = finalize({"intent": "AGENT_LOOP", "answer": "", "tool_result": {"skills": [
        fact("remove_other_schedule", {"error": "PERSON_NOT_FOUND", "message": "在已保存的同学课表中没有找到“王五”。",
                                       "candidates": [{"student_id": "sid-1", "name": "张三", "display_name": "张三"}]})]}})
    assert not_found["status"] == "needs_input" and not_found["error"]["code"] == "PERSON_NOT_FOUND"


def test_delete_requests_do_not_force_course_queries(isolated_engine):
    _, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三")})
    delete_run = graph.QueryRun(tools, "删除张三的课表", [])
    assert delete_run.other_scope()
    assert delete_run.scope_complete([]) is True  # 删除请求不得被要求先查课
    clear_run = graph.QueryRun(tools, "清空同学课表", [])
    assert clear_run.scope_complete([]) is True

    error_answer = graph.QueryRun(make_tools(), "删除王五的课表", []).other_error([
        fact("remove_other_schedule", {"error": "PERSON_NOT_FOUND", "message": "没有找到这位同学。",
                                       "candidates": []})])
    assert error_answer["_completion_status"] == "needs_input"


def test_remove_ambiguity_feeds_deterministic_person_choices():
    result = {"tool_result": {"skills": [
        fact("remove_other_schedule", {"error": "AMBIGUOUS_PERSON", "message": "匹配到多位同学",
                                       "candidates": [{"student_id": "sid-1", "name": "张三", "class_name": "软件2401"},
                                                      {"student_id": "sid-2", "name": "张三", "class_name": "软件2402"}]},
               person="张三")]}}
    people, request = clarification.person_choices(result)
    assert request == {"action": "remove", "person": "张三"}
    assert [p.student_id for p in people] == ["sid-1", "sid-2"]


def test_delete_flow_completes_without_course_query(isolated_engine, monkeypatch):
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三", "室友")})
    result, _sent, _state = replay(monkeypatch, "删除张三的课表", [
        reply_message(tool_calls=[tool_call("r1", "remove_other_schedule", '{"person": "张三"}')]),
        reply_message(content="已移除室友（张三）的课表，名单现在是空的。"),
    ], tools=tools)
    assert "已移除" in result["answer"] and fake.rows == {}
    assert result["skills"] == ["remove_other_schedule"]  # 未被迫补查课程


def test_clear_flow_requires_user_confirmation(isolated_engine, monkeypatch):
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三"),
                                 (1, "sid-b"): _saved_row("sid-b", "李四")})
    result, _sent, _state = replay(monkeypatch, "清空同学课表", [
        reply_message(tool_calls=[tool_call("c1", "clear_other_schedules", "{}")]),
        reply_message(content="确认要清空吗"),
    ], tools=tools)
    # other_error 直接采用工具返回的待确认消息，不依赖模型转述
    assert result["_completion_status"] == "needs_input"
    assert "确认清空" in result["answer"] and "2 位" in result["answer"]
    assert len(fake.rows) == 2


def test_clear_confirmed_execution_completes(isolated_engine, monkeypatch):
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三"),
                                 (1, "sid-b"): _saved_row("sid-b", "李四")})
    tools.clear_student_ids = ["sid-a", "sid-b"]
    result, _sent, _state = replay(monkeypatch, "确认", [
        reply_message(tool_calls=[tool_call("c1", "clear_other_schedules", '{"confirm": true, "expected_count": 2}')]),
        reply_message(content="已清空全部 2 位同学的课表。"),
    ], tools=tools)
    assert "已清空全部 2 位" in result["answer"]
    assert fake.rows == {}


def test_clear_cannot_be_confirmed_within_single_turn(isolated_engine, monkeypatch):
    """模型同轮获取人数后自行确认，也必须停在待用户确认状态。"""
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三"),
                                 (1, "sid-b"): _saved_row("sid-b", "李四")})
    result, _sent, _state = replay(monkeypatch, "清空同学课表，确认清空", [
        reply_message(tool_calls=[tool_call("c1", "clear_other_schedules", "{}")]),
        reply_message(tool_calls=[tool_call("c2", "clear_other_schedules", '{"confirm": true, "expected_count": 2}')]),
        reply_message(content="已清空全部 2 位同学的课表。"),
    ], tools=tools)
    assert "确认清空" in result["answer"]
    assert len(fake.rows) == 2
    from app.agent.completion import finalize
    assert finalize(dict(result))["status"] == "needs_input"


@pytest.mark.parametrize("arguments", ['{broken', '[]', 'null', '1'])
def test_person_choices_ignore_invalid_arguments(arguments):
    for skill in ("query_day_courses", "remove_other_schedule", "add_other_schedule"):
        result = {"tool_result": {"skills": [{"skill": skill, "arguments": arguments,
                  "result": {"error": "AMBIGUOUS_PERSON", "status": "ambiguous", "candidates": []}}]}}
        assert clarification.person_choices(result) == ([], {})


@pytest.mark.parametrize("answer", ["确认", "取消", "暂时不要"])
def test_clear_confirmation_is_owned_by_service(flow, monkeypatch, answer):
    db, redis, responses, requests, client, finish, say = flow
    rows = [_saved_row("sid-a", "张三"), _saved_row("sid-b", "李四")]
    monkeypatch.setattr(service, "_load_saved_rows", lambda conn, uid: list(rows))
    execute = db.execute
    def execute_clear(sql, params=None):
        from tests.fakes import FakeResult
        if "pg_advisory_xact_lock" in sql:
            return FakeResult([])
        if sql.startswith("DELETE FROM academic_others"):
            rows.clear()
            return FakeResult([])
        return execute(sql, params)
    monkeypatch.setattr(db, "execute", execute_clear)
    responses.extend([
        reply_message(tool_calls=[tool_call("clear", "clear_other_schedules", "{}")]),
        reply_message(content="确认清空吗？"),
    ])
    assert "确认清空" in say("清空同学课表")
    assert len(rows) == 2
    count = len(requests)
    result = say(answer)
    assert len(requests) == count  # 确认和取消均不再交给模型判断
    if answer == "确认":
        assert "已清空全部 2 位" in result and not rows
    else:
        assert len(rows) == 2


def test_clear_rejects_replaced_people_even_with_same_count():
    fake, tools = _others_tools({(1, "sid-b"): _saved_row("sid-b", "李四")})
    tools.clear_student_ids = ["sid-a"]
    result = tools.clear_other_schedules(True, 1)
    assert result["error"] == "CLEAR_NEEDS_CONFIRM"
    assert result["student_ids"] == ["sid-b"] and len(fake.rows) == 1


@pytest.mark.parametrize("args", ["{}", '{"person":""}', '{"person":"  ","student_id":" "}'])
def test_empty_removal_never_selects_only_saved_person(args):
    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三")})
    result = dispatch(build_skills(tools), "remove_other_schedule", args)
    assert result["error"] == "AMBIGUOUS_PERSON"
    assert len(result["candidates"]) == 1 and len(fake.rows) == 1


def test_week_comparison_uses_all_seven_dates_and_renders_verified_differences(monkeypatch):
    from app.agent import tools as tool_module

    fake, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三")})
    queried = []
    def other(row, target, period="all"):
        queried.append(target.isoformat())
        return {"date": target.isoformat(), "weekday": target.isoweekday(), "week": 1,
                "courses": [{"name": "高数", "start_time": "08:20", "end_time": "10:00",
                             "teacher": "王老师", "room": "A101"}] if target.weekday() == 0 else []}
    def mine(db, user_id, target, period, schedule_id):
        result = other({}, target)
        result["courses"] = [dict(c, room="A102") for c in result["courses"]]
        return result
    monkeypatch.setattr(service, "_materialize_other_row", other)
    monkeypatch.setattr(tool_module, "query_courses_by_date", mine)
    result = dispatch(build_skills(tools), "compare_other_week_courses", '{"person":"张三","date":"2026-09-09"}')
    assert result["start_date"] == "2026-09-07" and result["end_date"] == "2026-09-13"
    assert len(set(queried)) == 7
    assert len(result["days"][0]["other"]["courses"]) == 1
    assert len(result["days"][0]["me"]["courses"]) == 1
    facts = [fact("compare_other_week_courses", result)]
    answer = render_other_facts(facts, date(2026, 9, 8))
    assert "A101" in answer and "A102" in answer and "张三" in answer
    assert loop._facts_grounded(answer, facts, "张三下周什么课和我不一样")
    assert not loop._facts_grounded("张三下周没有课", facts, "张三下周什么课和我不一样")


def test_week_comparison_identical_courses_ignore_database_ids(monkeypatch):
    from app.agent import tools as tool_module

    _, tools = _others_tools({(1, "sid-a"): _saved_row("sid-a", "张三")})
    def courses(target, course_id):
        return {"date": target.isoformat(), "courses": [{"id": course_id, "name": "高数",
                "start_time": "08:20", "end_time": "10:00", "room": "A101", "teacher": "王老师"}]}
    monkeypatch.setattr(service, "_materialize_other_row", lambda row, target: courses(target, 1))
    monkeypatch.setattr(tool_module, "query_courses_by_date", lambda db, uid, target, *a: courses(target, 999))
    result = tools.compare_other_week_courses("张三", date(2026, 9, 9))
    assert all(not day["other"]["courses"] and not day["me"]["courses"] for day in result["days"])
    assert "完全一致" in render_other_facts([fact("compare_other_week_courses", result)], date(2026, 9, 8))


@pytest.mark.parametrize("skill", ["remove_other_schedule", "clear_other_schedules"])
@pytest.mark.parametrize("content,allowed", [("已移除张三的课表。", True),
                                              ("张三今天下午有课", False),
                                              ("已移除张三，他明天有课", False)])
def test_removal_facts_cannot_ground_course_claims(skill, content, allowed):
    facts = [fact(skill, {"ok": True, "removed": {"name": "张三"}})]
    assert loop._facts_grounded(content, facts, "删除张三的课表") is allowed


def test_other_error_only_suppresses_retry_with_same_arguments(isolated_engine):
    runtime = graph.QueryRun(make_tools(), "删除张三和李四的课表", [])
    failed = fact("remove_other_schedule", {"error": "PERSON_NOT_FOUND", "message": "没有找到张三"}, person="张三")
    success = fact("remove_other_schedule", {"ok": True}, person="李四")
    assert "没有找到张三" in runtime.other_error([failed, success])["answer"]
    retry = fact("remove_other_schedule", {"ok": True}, person="张三")
    assert runtime.other_error([failed, retry]) is None


def test_mixed_person_and_clear_questions_cannot_authorize_clear(flow, monkeypatch):
    from app.agent import service as agent_service
    db, redis, responses, requests, client, finish, say = flow
    candidates = [{"student_id": f"sid-{i}", "name": "张三", "class_name": f"软件240{i}"} for i in (1, 2)]
    remove = fact("remove_other_schedule", {"error": "AMBIGUOUS_PERSON", "message": "请选择张三的班级？",
                                            "candidates": candidates}, person="张三")
    clear = fact("clear_other_schedules", {"error": "CLEAR_NEEDS_CONFIRM", "status": "needs_input",
                                          "student_ids": ["sid-1", "sid-2"], "message": "确认清空全部吗？"})
    monkeypatch.setattr(agent_service, "handle_message", lambda *a, **kw: {
        "status": "needs_input", "answer": "请选择张三的班级？", "tool_result": {"skills": [remove, clear]}})
    delete = Mock(side_effect=AssertionError("must not clear"))
    monkeypatch.setattr(agent_service.ScheduleTools, "clear_other_schedules", delete)
    assert "班级" in say("删掉张三，其他的也清空")
    payload = json.loads(redis.get(clarification.key(7, "weixin_ilink", "sender", "bot")))
    assert payload["people"] and not payload["clear_student_ids"]
    # 即便遇到旧版本留下的混合状态，也不得把确认解释成清空。
    payload["clear_student_ids"] = ["sid-1", "sid-2"]
    redis.setex(clarification.key(7, "weixin_ilink", "sender", "bot"), 900, json.dumps(payload))
    assert "移除" in say("确认")
    delete.assert_not_called()


def test_removal_choice_handles_person_disappearing(flow, monkeypatch):
    from app.agent import service as agent_service
    from app.services.schedule_query import ScheduleQueryError

    db, redis, responses, requests, client, finish, say = flow
    def remove(self, person="", student_id=""):
        raise ScheduleQueryError("PERSON_NOT_FOUND", "这位同学已被移除。")
    monkeypatch.setattr(agent_service.ScheduleTools, "remove_other_schedule", remove)
    responses.extend([
        reply_message(tool_calls=[tool_call("remove", "remove_other_schedule", '{"person":"张三"}')]),
        reply_message(content="请选择同学？"),
    ])
    # 首次模型返回歧义结果，第二轮真实回放时模拟目标已消失。
    original_dispatch = loop._execute_tool_call
    def ambiguous(skills, call):
        from unittest.mock import patch
        with patch.object(agent_service.ScheduleTools, "remove_other_schedule", side_effect=ScheduleQueryError(
                "AMBIGUOUS_PERSON", "请选择同学？", [
                    {"student_id": "sid-a", "name": "张三", "class_name": "软件2401"},
                    {"student_id": "sid-b", "name": "张三", "class_name": "软件2402"}])):
            # 已构建的技能通过闭包读取 tools 方法。
            return original_dispatch(skills, call)
    monkeypatch.setattr(loop, "_execute_tool_call", ambiguous)
    assert "请选择" in say("删除张三的课表")
    count = len(requests)
    assert "已被移除" in say("第1位")
    assert len(requests) == count
