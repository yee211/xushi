from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.agent import orchestrator
from app.agent.sync import requested
from app.agent.tools import AgentContext, ScheduleTools
from app.services import academic_jobs


@pytest.mark.parametrize("message", ["同步课表", "帮我同步一下", "更新一下我的课表", "同步课表后帮我查明天的课", "先同步课表，完成后看看明天有什么课", "帮我更新一下课表，看看明天有什么课"])
def test_explicit_requests(message):
    assert requested(message)


@pytest.mark.parametrize("message", ["同步好了吗", "不要同步课表", "怎么同步课表", "课表好像没更新", "同步失败了", "可以同步课表吗", "上次同步课表", "同步课表了吗", "同步课表是不是需要登录", "为什么同步课表这么慢", "同步课表只是个例子", "同步课表，但别真的同步"])
def test_status_and_negation_do_not_submit(message):
    assert not requested(message)


def tools_with_binding(binding):
    db = MagicMock()
    db.__enter__.return_value = db
    db.execute.return_value.fetchone.return_value = binding
    return ScheduleTools(lambda: db, AgentContext(7, datetime(2026, 10, 14)))


def test_unauthorized_model_call_denied(monkeypatch):
    enqueue = MagicMock()
    monkeypatch.setattr(academic_jobs, "enqueue", enqueue)
    result = tools_with_binding(None).sync_schedule()
    assert result["error"] == "explicit_request_required"
    enqueue.assert_not_called()


def test_unbound_does_not_enqueue(monkeypatch):
    enqueue = MagicMock()
    monkeypatch.setattr(academic_jobs, "enqueue", enqueue)
    tools = tools_with_binding(None)
    tools.sync_authorized = True
    assert tools.sync_schedule()["error"] == "school_not_bound"
    enqueue.assert_not_called()


def test_submission_is_cached_and_does_not_call_model(monkeypatch):
    enqueue = MagicMock(return_value={"id": "job-1", "state": "queued", "term": "2026-2027-1"})
    monkeypatch.setattr(academic_jobs, "enqueue", enqueue)
    model = MagicMock(side_effect=AssertionError("model must not run"))
    monkeypatch.setattr(orchestrator, "run_agent", model)
    tools = tools_with_binding({"student": {"default_term": "2026-2027-1"}, "last_synced_term": None})
    result = orchestrator.handle_message("同步课表后帮我查明天的课", tools)
    assert result["tool_result"]["job_id"] == "job-1"
    assert "同步完成后" in result["answer"]
    assert tools.sync_schedule() == result["tool_result"]
    enqueue.assert_called_once_with(7, "2026-2027-1", True, cooldown_seconds=30)
    model.assert_not_called()


def test_uncertain_submission_is_not_retried(monkeypatch):
    enqueue = MagicMock(side_effect=TimeoutError())
    monkeypatch.setattr(academic_jobs, "enqueue", enqueue)
    tools = tools_with_binding({"student": {}, "last_synced_term": "2026-2027-1"})
    tools.sync_authorized = True
    result = tools.sync_schedule()
    assert result["error"] == "submission_unknown"
    assert "查询同步进度" in result["message"]
    assert tools.sync_schedule() == result
    enqueue.assert_called_once()


def test_cooldown_checked_under_existing_user_lock(monkeypatch):
    db = MagicMock()
    db.__enter__.return_value = db
    binding = {"student": {"id": "student"}, "revision": 1, "updated_at": "now"}
    job = dict.fromkeys(("id", "term", "state", "attempts", "result", "error", "created_at", "updated_at", "phase", "started_at"))
    job.update(id="job-1", term="2026-2027-1", state="succeeded")
    db.execute.return_value.fetchone.side_effect = [binding, None, job]
    monkeypatch.setattr(academic_jobs, "connect", lambda: db)
    lock = MagicMock()
    monkeypatch.setattr(academic_jobs.academic_binding, "lock_user", lock)
    assert academic_jobs.enqueue(7, "2026-2027-1", True, cooldown_seconds=30)["id"] == "job-1"
    lock.assert_called_once()
    assert not any("INSERT INTO" in call.args[0] for call in db.execute.call_args_list)


def test_sync_claims_require_matching_terminal_state():
    from app.agent.loop import _facts_grounded

    def status(state):
        return [{"skill": "get_schedule_status", "result": {"sync_job": {"state": state}}}]
    assert not _facts_grounded("已提交同步任务", [], "你好")
    assert not _facts_grounded("同步成功", status("queued"), "同步好了吗")
    assert not _facts_grounded("课表已经更新", status("failed"), "同步好了吗")
    assert _facts_grounded("同步成功", status("succeeded"), "同步好了吗")
    assert _facts_grounded("已提交同步任务", status("queued"), "同步好了吗")


def test_future_completion_is_not_a_success_claim():
    from app.agent.loop import _facts_grounded

    facts = [{"skill": "get_schedule_status", "result": {"sync_job": {"state": "queued"}}}]
    assert _facts_grounded("等待同步完成后再查询课表", facts, "同步好了吗")
    assert _facts_grounded("尚未同步完成", facts, "同步好了吗")
