from datetime import datetime
from unittest.mock import Mock

import pytest

from app.agent.peer_sync import handle, target
from app.agent.tools import AgentContext, ScheduleTools


@pytest.mark.parametrize("message, expected", [
    ("同步课表", None), ("同步我的课表", None),
    ("帮我同步张三的课表", ("person", "张三")),
    ("更新一下室友课表", ("person", "室友")),
    ("同步全部同学课表", ("all", "")),
    ("同步所有已保存的同学课表", ("all", "")),
    ("同步同学课表", ("clarify", "")),
    ("不要同步张三的课表", None),
    ("同步张三的课表了吗", None),
    ("怎么同步张三的课表", None),
    ("同步张三的课表，但别真的同步", None),
])
def test_target(message, expected):
    assert target(message) == expected


def test_peer_tools_require_matching_authorization():
    tools = ScheduleTools(None, AgentContext(1, datetime(2026, 10, 25)))
    assert tools.sync_other_schedule("张三")["error"] == "explicit_request_required"
    tools.other_sync_authorized = ("person", "张三")
    assert tools.sync_all_other_schedules()["error"] == "explicit_request_required"
    assert tools.sync_other_schedule("李四")["error"] == "explicit_request_required"
    assert tools.sync_schedule()["error"] == "explicit_request_required"


def test_route_all_never_submits_own_schedule():
    tools = Mock()
    tools.sync_all_other_schedules.return_value = {"ok": True, "message": "已提交"}
    assert handle("同步全部同学课表", tools)["tool_result"]["ok"]
    tools.sync_all_other_schedules.assert_called_once_with()
    tools.sync_schedule.assert_not_called()
    tools.sync_other_schedule.assert_not_called()


def test_single_enqueue_is_scoped_and_cached(monkeypatch):
    from contextlib import nullcontext

    from app.services import academic_other_jobs, academic_others
    tools = ScheduleTools(None, AgentContext(7, datetime(2026, 10, 25)))
    tools.other_sync_authorized = ("person", "张三")
    monkeypatch.setattr(tools, "_connection", lambda: nullcontext(None))
    monkeypatch.setattr(academic_others, "_load_saved_rows", lambda *_: [{"student_id": "peer", "remark": "张三"}])
    enqueue = Mock(return_value={"id": "job", "state": "queued", "total": 1})
    monkeypatch.setattr(academic_other_jobs, "enqueue", enqueue)
    assert tools.sync_other_schedule("张三")["job_id"] == "job"
    tools.sync_other_schedule("张三")
    enqueue.assert_called_once_with(7, student_ids=["peer"])


@pytest.mark.parametrize("message", ["同步学校最新课表", "同步自己的课表", "更新我自己的课表"])
def test_own_scope(message):
    from app.agent.sync import requested
    assert target(message) is None
    assert requested(message)


def test_peer_status_followup_uses_peer_job():
    from langchain_core.messages import AIMessage, HumanMessage
    tools = Mock()
    tools.get_other_schedule_status.return_value = {"ok": True, "job": None}
    history = [HumanMessage(content='同步张三的课表 [已解析上下文：{"intent": "SYNC_OTHER_SCHEDULE", "job_id": "peer-job"}]'),
               AIMessage(content="正在后台同步")]
    assert handle("同步好了吗", tools, history)["intent"] == "OTHER_SCHEDULE_STATUS"
    tools.get_other_schedule_status.assert_called_once_with("peer-job")
    tools.get_schedule_status.assert_not_called()
    tools.sync_schedule.assert_not_called()


def test_explicit_self_status_overrides_peer_history():
    from langchain_core.messages import HumanMessage
    tools = Mock()
    history = [HumanMessage(content='{"intent": "SYNC_OTHER_SCHEDULE", "job_id": "peer-job"}')]
    assert handle("我的同步好了吗", tools, history) is None
    tools.get_other_schedule_status.assert_not_called()


def test_explicit_peer_status_does_not_submit():
    tools = Mock()
    tools.get_other_schedule_status.return_value = {"ok": True, "job": None}
    assert handle("全部同学课表同步好了吗", tools)["intent"] == "OTHER_SCHEDULE_STATUS"
    tools.get_other_schedule_status.assert_called_once_with(None)
    tools.sync_all_other_schedules.assert_not_called()


def test_own_sync_after_peer_sync_does_not_become_status():
    from langchain_core.messages import HumanMessage
    tools = Mock()
    history = [HumanMessage(content='{"intent": "SYNC_OTHER_SCHEDULE", "job_id": "peer-job"}')]
    assert handle("同步课表", tools, history) is None
    tools.get_other_schedule_status.assert_not_called()


def test_skills_distinguish_sync_targets():
    from app.agent.skills import build_skills
    tools = ScheduleTools(None, AgentContext(7, datetime(2026, 10, 25)))
    skills = {s.name: s for s in build_skills(tools)}
    assert skills["sync_other_schedule"].required == ("person",)
    assert skills["sync_all_other_schedules"].required == ()
    assert "自己" in skills["sync_schedule"].description
    assert "不含自己" in skills["sync_all_other_schedules"].description


@pytest.mark.parametrize("message", ["同步张三的课表好了吗", "张三的课表同步好了吗"])
def test_named_peer_status_is_not_own_status(message):
    tools = Mock()
    tools.get_other_schedule_status.return_value = {"ok": True, "job": None}
    assert handle(message, tools)["intent"] == "OTHER_SCHEDULE_STATUS"
    tools.get_other_schedule_status.assert_called_once_with(person="张三")
    tools.sync_other_schedule.assert_not_called()


def test_unknown_peer_status_does_not_borrow_another_person(monkeypatch):
    from contextlib import nullcontext

    from app.services import academic_other_jobs, academic_others
    tools = ScheduleTools(None, AgentContext(7, datetime(2026, 10, 25)))
    monkeypatch.setattr(tools, "_connection", lambda: nullcontext(None))
    monkeypatch.setattr(academic_others, "_load_saved_rows", lambda *_: [{"student_id": "a", "remark": "张三"}])
    monkeypatch.setattr(academic_other_jobs, "read", lambda *_: {"items": [{"student_id": "b"}]})
    assert tools.get_other_schedule_status(person="张三")["error"] == "person_not_in_job"
