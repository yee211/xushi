"""Fault injection and boundary tests for the deep audit repairs."""
import base64
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import rate_limit
from app.auth import deps
from app.auth.jwt import create_token
from app.channels.weixin import store
from app.excel import _grid_to_rows
from app.html_parser import MatrixTableExtractor
from app.services import academic, academic_sync_notifications, llm_config


def request(peer, forwarded):
    return Request({"type": "http", "client": (peer, 1234),
                    "headers": [(b"x-forwarded-for", forwarded.encode())]})


@pytest.mark.parametrize("peer,forwarded,expected", [
    ("127.0.0.1", "1.1.1.1, 8.8.8.8", "8.8.8.8"),
    ("8.8.8.8", "1.1.1.1", "8.8.8.8"),
    ("127.0.0.1", "invalid", "127.0.0.1"),
])
def test_proxy_chain_never_trusts_client_prefix(monkeypatch, peer, forwarded, expected):
    monkeypatch.setattr(rate_limit, "settings", replace(rate_limit.settings, trust_proxy_headers=True))
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    assert rate_limit.client_ip(request(peer, forwarded)) == expected


def test_redis_failure_cannot_grow_memory_without_bound():
    limiter = rate_limit.SlidingWindowLimiter(1, 60)
    for index in range(10020):
        limiter._hit_memory(str(index), 1)
    assert len(limiter._hits) <= 10001


def test_corrupt_account_does_not_hide_valid_accounts(monkeypatch):
    monkeypatch.setenv("WEIXIN_ILINK_CREDENTIAL_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    db = MagicMock()
    common = {"api_base_url": "https://example.com", "admin_user_id": "", "update_cursor": ""}
    db.execute.return_value.fetchall.return_value = [
        dict(common, account_id="bad", bot_token_encrypted="broken"),
        dict(common, account_id="good", bot_token_encrypted=store.encrypt_token("token")),
    ]
    accounts = store.load_accounts(db)
    assert [item[0].account_id for item in accounts] == ["good"]


def test_revoked_jwt_rejected_but_new_login_accepted(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(deps, "connect", lambda: nullcontext(db))
    old = create_token(7, "test")
    db.execute.return_value.fetchone.return_value = {"auth_revoked_at": datetime.now(UTC) + timedelta(seconds=1)}
    with pytest.raises(HTTPException) as error:
        deps._user_from_jwt(old)
    assert error.value.status_code == 401
    db.execute.return_value.fetchone.return_value = {"auth_revoked_at": datetime.now(UTC) - timedelta(seconds=1)}
    assert deps._user_from_jwt(create_token(7, "test"))["id"] == 7


@pytest.mark.parametrize("span", [100000000, 1001])
def test_html_span_rejected_before_matrix_expansion(span):
    parser = MatrixTableExtractor()
    with pytest.raises(ValueError, match="limits"):
        parser.feed(f'<table><tr><td colspan="{span}">test</td></tr></table>')
    with pytest.raises(ValueError, match="limits"):
        _grid_to_rows([[('test', span, 1)]])


def test_missing_week_data_is_not_an_authoritative_empty_schedule():
    import httpx

    from tests.test_academic import report, timetable_handler
    def handler(request):
        if request.url.path == "/report/sample":
            return httpx.Response(200, text=report(""))
        if request.url.path.endswith("getXskb"):
            return httpx.Response(200, json={"ret": 0})
        return timetable_handler(request)
    with academic.CcsutClient({"Cookie": "test"}, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(academic.AcademicError) as error:
            client.schedule("student123", "2026-2027-1")
    assert error.value.code == "schedule_incomplete"


def test_rejected_notification_subscription_does_not_promise_delivery():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    target = dict(provider="weixin_ilink", sender_id="sender", account_id="bot", message_id="message")
    assert academic_sync_notifications.subscribe(db, dict(id="job", user_id=7, state="queued"), target) is False


def test_save_llm_config_never_reuses_secret_at_changed_endpoint(monkeypatch):
    monkeypatch.setattr(llm_config, "get_llm_config", lambda scope: {"base_url": "https://model.example/v1", "api_key": "saved-secret"})
    with pytest.raises(ValueError, match="explicitly"):
        llm_config.save_llm_config("agent", {"base_url": "https://attacker.example/v1"}, None)


def test_negative_sync_requests_are_not_status_queries():
    from app.agent.sync import status_requested
    assert not status_requested("不要同步")
    assert not status_requested("取消同步")


def test_complete_answer_with_conversational_intro_is_not_pending():
    from app.agent.completion import finalize
    result = finalize({"intent": "QUERY_DAY", "answer": "我帮你看看，今天第1节有高数，在A101。"})
    assert result["status"] == "completed"


def test_name_list_failure_does_not_block_my_schedule(monkeypatch):
    from app.agent import orchestrator
    from app.agent.tools import AgentContext
    tools = MagicMock()
    tools.context = AgentContext(7, datetime(2026, 10, 12, tzinfo=UTC))
    tools.list_other_people.side_effect = RuntimeError("unavailable")
    tools.get_courses_by_date.return_value = {"date": "2026-10-12", "weekday": 1, "week": 1, "courses": []}
    result = orchestrator.handle_message("今天有什么课", tools)
    assert result.get("error", {}).get("code") != "service_unavailable"


@pytest.mark.parametrize("payload", [{"choices": []}, {"choices": [{"message": {"content": None}}]}])
def test_malformed_model_success_falls_back_and_counts_failure(monkeypatch, payload):
    from app.agent import intent_ai, polish_ai
    from app.agent.circuit_breaker import llm_circuit_breaker
    response = MagicMock()
    response.json.return_value = payload
    failure = MagicMock()
    monkeypatch.setattr(llm_circuit_breaker, "record_failure", failure)
    monkeypatch.setattr(intent_ai, "get_llm_config", lambda scope: {"base_url": "https://model.example", "api_key": "key", "model": "model"})
    monkeypatch.setattr(intent_ai, "_post_llm", lambda *args, **kwargs: response)
    monkeypatch.setattr(polish_ai, "polish_config", lambda: ("https://model.example", "key", "model", 5, 100, False))
    monkeypatch.setattr(polish_ai, "_post_llm", lambda *args, **kwargs: response)
    assert intent_ai.extract_intent("test", date(2026, 10, 12)) is None
    assert polish_ai.polish_answer("test", "answer", {}) is None
    assert polish_ai.small_talk("test") is None
    assert failure.call_count == 3


def test_resolved_person_error_does_not_override_later_success():
    import json

    from app.agent.completion import finalize
    from app.agent.graph import QueryRun
    from app.agent.other_reply import render_other_facts
    from tests.test_agent_loop import make_tools
    run = QueryRun(make_tools(), "张三明天有什么课", None, credentials=("url", "key", "model"), config={"test": True})
    facts = [
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "室友", "date": "2026-09-09"}),
         "result": {"error": "PERSON_NOT_FOUND", "message": "未找到室友"}},
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "张三", "date": "2026-09-09"}),
         "result": {"date": "2026-09-09", "weekday": 3, "week": 1, "courses": [], "person": {"display_name": "张三"}}},
    ]
    assert run.other_error(facts) is None
    assert facts[0]["_superseded"]
    text = render_other_facts(facts, date(2026, 9, 9))
    assert text and "未找到室友" not in text
    assert finalize({"intent": "AGENT_LOOP", "answer": text, "tool_result": {"skills": facts}})["status"] == "completed"


def test_next_course_only_queries_seven_natural_days(monkeypatch):
    from app.services import schedule_query
    seen = []
    def query(db, user, target, *args):
        seen.append(target)
        return {"courses": []}
    monkeypatch.setattr(schedule_query, "query_courses_by_date", query)
    schedule_query.next_course(None, 7, datetime(2026, 10, 12, tzinfo=UTC))
    assert len(seen) == 7 and seen[-1] == date(2026, 10, 18)


def test_week_comparison_does_not_claim_equal_when_all_days_unavailable():
    from app.agent.other_reply import render_other_facts
    facts = [{"skill": "compare_other_week_courses", "result": {
        "person": {"display_name": "同学"}, "start_date": "2026-10-12", "end_date": "2026-10-18",
        "days": [], "skipped_dates": ["2026-10-12"],
    }}]
    text = render_other_facts(facts, date(2026, 10, 12))
    assert "没有双方均在学期内的可比较日期" in text
    assert "课程完全一致" not in text


def test_many_tables_cannot_bypass_total_expansion_budget(tmp_path):
    from app.excel import read_sheets
    content = '<table><tr><td colspan="100" rowspan="100">test</td></tr></table>' * 11
    with pytest.raises(ValueError, match="total import limits"):
        MatrixTableExtractor().feed(content)
    upload = tmp_path / "tables.html"
    upload.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="total import limits"):
        read_sheets(upload, "html")
