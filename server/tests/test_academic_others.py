import json
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app.services import academic_others as service


class Result:
    def __init__(self, value): self.value = value
    def fetchone(self): return self.value
    def fetchall(self): return self.value

class Db:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.version = 0
    def execute(self, sql, params):
        self.calls.append(sql)
        if "pg_advisory_xact_lock" in sql:
            return Result(None)
        if "COUNT(*) AS total" in sql:
            sid, uid = params
            return Result({"total": sum(k[0] == uid for k in self.rows), "present": int((uid, sid) in self.rows)})
        if sql.startswith("SELECT * FROM academic_others"):
            row = self.rows.get(tuple(params))
            return Result(dict(row) if row else None)
        if sql.startswith("UPDATE academic_others SET snapshot"):
            snapshot, uid, sid, term, version = params
            row = self.rows.get((uid, sid))
            if not row or row['term'] != term or row['updated_at'] != version:
                return Result(None)
            self.version += 1
            row.update(snapshot=json.loads(snapshot), updated_at=self.version)
            return Result(dict(row))
        if sql.startswith("INSERT"):
            uid, sid, term, remark, snapshot, _ = params
            if remark is None:
                remark = self.rows.get((uid, sid), {}).get("remark", "")
            self.version += 1
            row = dict(student_id=sid, term=term, remark=remark, snapshot=json.loads(snapshot), updated_at=self.version)
            self.rows[uid, sid] = row
            return Result(row)
        if sql.startswith("DELETE"):
            self.rows.pop(tuple(params), None)
            return Result(None)
        return Result([v for (uid, sid), v in self.rows.items() if uid == params[0]])

@pytest.fixture
def db(monkeypatch):
    db = Db()
    @contextmanager
    def connect(): yield db
    monkeypatch.setattr(service, "connect", connect)
    monkeypatch.setattr(service.query_limiter, "hit", lambda key: (True, 0))
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: {"complete": True, "courses": []})
    return db

def test_multiple_people_and_account_isolation(db):
    service.save(1, "student-a", "2026-2027-1")
    service.save(1, "student-b", "2026-2027-1")
    service.save(2, "student-a", "2026-2027-1")
    service.save(1, "student-a", "2026-2027-2", " 室友 ")
    assert len(service.list_saved(1)["people"]) == 2
    assert db.rows[1, "student-a"]["term"] == "2026-2027-2"
    assert db.rows[1, "student-a"]["remark"] == "室友"
    service.remove(1, "student-a")
    assert (2, "student-a") in db.rows
    assert (1, "student-b") in db.rows
    assert all("academic_bindings" not in sql and "DELETE FROM schedules" not in sql for sql in db.calls)

@pytest.mark.parametrize("snapshot", [{"stale": True, "complete": True}, {"complete": False}])
def test_failed_update_preserves_existing(db, monkeypatch, snapshot):
    service.save(1, "student-a", "2026-2027-1")
    old = dict(db.rows)
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: snapshot)
    with pytest.raises((HTTPException, service.academic.AcademicError)):
        service.save(1, "student-a", "2026-2027-2")
    assert db.rows == old


def test_query_has_scoped_queue_budget_and_keeps_error_reason(monkeypatch):
    from app.services import academic_rate_limit
    previous = academic_rate_limit._query_wait.get()
    def get_schedule(*args):
        assert academic_rate_limit._query_wait.get() == 15
        return {"complete": True, "stale": True, "refresh_error": {"code": "upstream_timeout", "message": "学校查询排队超时"}}
    monkeypatch.setattr(service.academic, "get_schedule", get_schedule)
    with pytest.raises(service.academic.AcademicError) as caught:
        service.query("student-a", "2026-2027-1")
    assert caught.value.code == "upstream_timeout"
    assert "排队超时" in caught.value.message
    assert academic_rate_limit._query_wait.get() == previous


def _sample_snapshot(name, class_name, courses):
    return {
        "complete": True,
        "term": "2026-2027-1",
        "start_date": "2026-09-07",
        "end_date": "2027-01-24",
        "student": {"id": f"sid-{name}", "name": name, "class_name": class_name, "major_name": "软件工程", "grade": "2024"},
        "courses": courses,
    }


@pytest.mark.parametrize("code", ["OUTSIDE_TERM", "AMBIGUOUS_SCHEDULE", "INVALID_SECTION"])
def test_group_availability_requires_my_schedule(db, monkeypatch, code):
    from datetime import date

    from app.services.schedule_query import ScheduleQueryError

    snapshot = _sample_snapshot("李四", "软件2401", [])
    monkeypatch.setattr(service.academic, "get_schedule", lambda *args: snapshot)
    service.save(1, "student-a", "2026-2027-1", "室友")
    candidates = [{"id": 1, "name": "课表一"}, {"id": 2, "name": "课表二"}]

    def unavailable(*args):
        raise ScheduleQueryError(code, "我的课表不可用", candidates)

    monkeypatch.setattr(service, "query_courses_by_date", unavailable)
    with pytest.raises(ScheduleQueryError) as caught:
        service.check_group_availability(db, 1, date(2026, 9, 9), people_queries=["室友"])
    assert caught.value.code == code
    assert caught.value.candidates == candidates
    assert "不能计算共同空闲" in caught.value.message
    # Explicitly excluding me still allows a query of the friend's valid data.
    result = service.check_group_availability(db, 1, date(2026, 9, 9), include_me=False)
    assert len(result["participants"]) == 1


def test_group_availability_does_not_drop_other_outside_term(db, monkeypatch):
    from datetime import date

    from app.services.schedule_query import ScheduleQueryError

    snapshots = {
        "student-a": _sample_snapshot("李四", "软件2401", []),
        "student-b": dict(_sample_snapshot("王五", "软件2402", []), end_date="2026-09-08"),
    }
    monkeypatch.setattr(service.academic, "get_schedule", lambda sid, *args: snapshots[sid])
    service.save(1, "student-a", "2026-2027-1", "室友")
    service.save(1, "student-b", "2026-2027-1", "搭子")
    with pytest.raises(ScheduleQueryError) as caught:
        service.check_group_availability(db, 1, date(2026, 9, 9), include_me=False)
    assert caught.value.code == "OUTSIDE_TERM"
    assert "王五" in caught.value.message
    assert "不能计算共同空闲" in caught.value.message


@pytest.mark.parametrize("model_enabled", [False, True])
@pytest.mark.parametrize("message,history", [
    ("明天下午我和室友都有空吗", []),
    ("明天室友有什么课", []),
    ("明天下午李四有什么课", []),
    ("明天下午球搭子有空吗", []),
    ("明天呢", [{"role": "user", "content": "今天李四有什么课"}]),
])
def test_other_query_fallback_never_reads_personal_schedule(monkeypatch, model_enabled, message, history):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.agent import orchestrator
    from app.agent.circuit_breaker import llm_circuit_breaker

    llm_circuit_breaker.reset()
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: model_enabled)
    monkeypatch.setattr(orchestrator, "run_agent", lambda *args: None)
    tools = Mock()
    tools.context = SimpleNamespace(now=datetime(2026, 9, 8, 13))
    tools.list_other_people.return_value = {"people": [{"name": "李四", "remark": "球搭子"}]}
    result = orchestrator.handle_message(message, tools, history)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "other_query_unavailable"
    tools.get_courses_by_date.assert_not_called()
    tools.get_next_course.assert_not_called()
    tools.list_course_catalog.assert_not_called()


def test_personal_availability_still_works_without_model(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.agent import orchestrator

    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(orchestrator, "available", lambda: False)
    tools = Mock()
    tools.context = SimpleNamespace(now=datetime(2026, 9, 8, 13))
    tools.list_other_people.return_value = {"people": [{"name": "李四", "remark": "室友"}]}
    tools.get_courses_by_date.return_value = {"date": "2026-09-09", "weekday": 3, "courses": []}
    result = orchestrator.handle_message("明天下午我有空吗", tools)
    assert result["status"] == "completed"
    assert "你有空" in result["answer"]
    tools.get_courses_by_date.assert_called_once()


def test_agent_query_other_courses_and_group_availability(db, monkeypatch):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from app.agent import loop, orchestrator
    from app.agent.circuit_breaker import llm_circuit_breaker
    from app.agent.tools import AgentContext, ScheduleTools
    from tests.test_agent_loop import FakeResponse, reply_message, tool_call

    llm_circuit_breaker.reset()

    snapshots = {
        "student-a": _sample_snapshot("李四", "软件2401", [
            {"name": "数据结构", "teacher": "王博", "room": "B202", "weekday": 3, "start_section": 5, "end_section": 6, "weeks": [1, 2, 3]},
        ]),
        "student-b": _sample_snapshot("王五", "软件2402", []),
    }
    monkeypatch.setattr(service.academic, "get_schedule", lambda sid, *a: snapshots[sid])
    service.save(1, "student-a", "2026-2027-1", "室友")
    service.save(1, "student-b", "2026-2027-1", "球搭子")

    # Attach user's own schedule (has class on weekday 3 sections 1-2)
    class CombinedDb:
        def execute(self, sql, params):
            if "FROM academic_others" in sql or sql.startswith("INSERT INTO academic_others"):
                return db.execute(sql, params)
            if "FROM schedules" in sql:
                return Result([{"id": 1, "name": "我的课表", "term": "2026-2027-1",
                                "start_date": date(2026, 9, 7), "end_date": date(2027, 1, 24),
                                "variant_type": "original", "source_schedule_id": None}])
            if "FROM courses" in sql:
                return Result([{"id": 10, "name": "高等数学", "teacher": "张老师", "room": "A101",
                                "weekday": 3, "start_section": 1, "end_section": 2, "weeks": [1, 2, 3]}])
            if "FROM course_adjustments" in sql:
                return Result([])
            if "FROM academic_bindings" in sql:
                return Result({"last_synced_term": "2026-2027-1"})
            raise AssertionError(sql)

    tools = ScheduleTools(CombinedDb(), AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai"))))

    # 1. Direct tool verification: query_other_day_courses by remark "室友"
    other_day = tools.query_other_day_courses("室友", date(2026, 9, 9), "afternoon")
    assert tools.query_other_day_courses("室友(李四)", date(2026, 9, 9), "afternoon")["person"]["name"] == "李四"
    assert tools.query_other_day_courses("室友 · 李四", date(2026, 9, 9), "afternoon")["person"]["name"] == "李四"
    assert other_day["person"]["name"] == "李四"
    assert len(other_day["courses"]) == 1
    assert other_day["courses"][0]["name"] == "数据结构"
    assert other_day["courses"][0]["start_time"] == "14:00"

    # 2. Direct tool verification: check_group_availability on 2026-09-09 afternoon
    # Me: free in afternoon (sections 5-8); 李四: busy 5-6, free 7-8; 王五: completely free
    avail = tools.check_group_availability(date(2026, 9, 9), "afternoon")
    assert "我" in avail["completely_free_people"]
    assert "球搭子（王五）" in avail["completely_free_people"]
    assert "室友（李四）" in avail["busy_people"]
    assert avail["common_free_slots"] == [{"start_section": 7, "end_section": 8, "start_time": "16:00", "end_time": "17:40"}]

    # 3. Full Agent Loop verification: asking "明天下午室友有什么课"
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: True)
    monkeypatch.setattr(orchestrator, "run_agent", loop.run)
    monkeypatch.setattr(loop, "agent_config", lambda: ("https://api.deepseek.com/v1", "test-key", "test-model"))
    monkeypatch.setattr(loop, "get_llm_config", lambda scope: {})
    replies = [
        reply_message(tool_calls=[tool_call("c1", "query_other_day_courses", '{"person":"室友","date":"2026-09-09","period":"afternoon"}')]),
        reply_message(content=json.dumps({
            "status": "completed",
            "answer": "室友（李四）明天下午有1节课：\n• 14:00–15:40 数据结构，王博，B202",
            "task_id": None,
        }, ensure_ascii=False)),
    ]
    monkeypatch.setattr(loop, "_post_llm", lambda url, **kw: FakeResponse(replies.pop(0)))
    res1 = orchestrator.handle_message("明天下午室友有什么课", tools)
    assert res1["intent"] == "AGENT_LOOP"
    assert res1["status"] == "completed"
    assert "数据结构" in res1["answer"] and "B202" in res1["answer"]

    # 4. Full Agent Loop verification: asking "明天下午我和室友什么时候都有空"
    replies2 = [
        reply_message(tool_calls=[tool_call("c2", "check_group_availability", '{"date":"2026-09-09","period":"afternoon","people":["室友"],"include_me":true}')]),
        reply_message(content='{"status":"completed","answer":"明天下午你没课，室友（李四）14:00–15:40 有数据结构课，你们的共同空闲时间是第7–8节（16:00–17:40）。","task_id":null}'),
    ]
    monkeypatch.setattr(loop, "_post_llm", lambda url, **kw: FakeResponse(replies2.pop(0)))
    res2 = orchestrator.handle_message("明天下午我和室友什么时候都有空", tools)
    assert res2["status"] == "completed"
    assert "16:00–17:40" in res2["answer"]


def test_agent_add_other_schedule_disambiguation_and_save(db, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.agent import loop, orchestrator
    from app.agent.circuit_breaker import llm_circuit_breaker
    from app.agent.tools import AgentContext, ScheduleTools
    from tests.test_agent_loop import FakeResponse, reply_message, tool_call

    llm_circuit_breaker.reset()

    students_found = [
        {"id": "sid-zs-1", "name": "张三", "grade": "2024", "class_name": "软件2401", "major_name": "软件工程", "student_number_display": "20240101", "default_term": "2026-2027-1"},
        {"id": "sid-zs-2", "name": "张三", "grade": "2025", "class_name": "计科2502", "major_name": "计算机科学与技术", "student_number_display": "20250202", "default_term": "2026-2027-1"},
    ]
    monkeypatch.setattr(service.academic, "search_keyword", lambda kw: {"students": students_found if kw == "张三" else [students_found[0]]})
    monkeypatch.setattr(service.academic, "student_context", lambda sid: next(s for s in students_found if s["id"] == sid))
    monkeypatch.setattr(service.academic, "get_schedule", lambda sid, term, refresh=False: _sample_snapshot("张三", "软件2401", []))

    tools = ScheduleTools(db, AgentContext(user_id=1, now=datetime(2026, 9, 8, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai"))))
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: True)
    monkeypatch.setattr(orchestrator, "run_agent", loop.run)
    monkeypatch.setattr(loop, "agent_config", lambda: ("https://api.deepseek.com/v1", "test-key", "test-model"))
    monkeypatch.setattr(loop, "get_llm_config", lambda scope: {})

    # Round 1: multiple matches -> returns needs_input
    replies1 = [
        reply_message(tool_calls=[tool_call("add1", "add_other_schedule", '{"keyword":"张三","remark":"搭子"}')]),
        reply_message(content=json.dumps({
            "status": "needs_input",
            "answer": "找到 2 位叫张三的同学：1. 2024级软件2401（20240101）；2. 2025级计科2502（20250202）。请问要添加哪一位？",
            "task_id": None,
        }, ensure_ascii=False)),
    ]
    monkeypatch.setattr(loop, "_post_llm", lambda url, **kw: FakeResponse(replies1.pop(0)))
    res_ambig = orchestrator.handle_message("帮我加一下张三的课表，备注搭子", tools)
    assert res_ambig["status"] == "needs_input"
    assert "软件2401" in res_ambig["answer"]
    assert (1, "sid-zs-1") not in db.rows

    # Round 2: user confirms -> saves into academic_others
    replies2 = [
        reply_message(tool_calls=[tool_call("add2", "add_other_schedule", '{"student_id":"sid-zs-1","remark":"搭子"}')]),
        reply_message(content='{"status":"completed","answer":"已为你添加搭子（张三，软件2401）的课表。","task_id":null}'),
    ]
    monkeypatch.setattr(loop, "_post_llm", lambda url, **kw: FakeResponse(replies2.pop(0)))
    res_saved = orchestrator.handle_message("软件2401那个", tools)
    assert res_saved["status"] == "completed"
    assert (1, "sid-zs-1") in db.rows
    assert db.rows[1, "sid-zs-1"]["remark"] == "搭子"

