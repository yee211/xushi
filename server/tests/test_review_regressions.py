"""Follow-up regressions for the audit corrections, with external IO isolated."""
import json

import pytest
from starlette.requests import Request

from app.agent.completion import finalize, promises_work
from app.services import academic, llm_config


@pytest.mark.parametrize("text", [
    "我帮你看看明天的课：1. 高数 08:20–09:05 南313",
    "我帮你看看明天的课: 高数 08:20–09:05 南313",
    "我帮你看看，今天第1节有高数，在A101。",
])
def test_conversational_opening_with_completed_facts_is_not_pending(text):
    assert not promises_work(text)
    assert finalize({"intent": "QUERY_DAY", "answer": text})["answer"] == text


@pytest.mark.parametrize("text", ["我帮你看看明天08:20的课", "我帮你查询一下", "我帮你看看明天的课"])
def test_opening_without_result_is_still_pending(text):
    assert promises_work(text)


@pytest.mark.parametrize("joiner", ["，再查", "，还有", "，另外查", "，顺便查", "和", "、", "？", "，"])
def test_other_person_success_does_not_hide_requested_person_failure(joiner):
    from app.agent.graph import QueryRun
    from tests.test_agent_loop import make_tools
    run = QueryRun(make_tools(), "查室友的课" + joiner + "张三的课", None,
                   credentials=("url", "key", "model"), config={"test": True})
    facts = [
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "室友", "date": "2026-10-12"}),
         "result": {"error": "PERSON_NOT_FOUND", "message": "未找到室友"}},
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "张三", "date": "2026-10-12"}),
         "result": {"courses": []}},
    ]
    assert run.other_error(facts)["answer"] == "未找到室友"
    assert not facts[0].get("_superseded")


@pytest.mark.parametrize("question", ["再查一下张三的课", "张三明天有什么课"])
def test_sequence_word_retry_with_single_target_supersedes_stale_error(question):
    from app.agent.graph import QueryRun
    from tests.test_agent_loop import make_tools
    run = QueryRun(make_tools(), question, None, credentials=("url", "key", "model"), config={"test": True})
    facts = [
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "室友", "date": "2026-10-12"}),
         "result": {"error": "PERSON_NOT_FOUND", "message": "未找到室友"}},
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "张三", "date": "2026-10-12"}),
         "result": {"courses": []}},
    ]
    assert run.other_error(facts) is None
    assert facts[0]["_superseded"]


def test_sequence_word_with_unmatched_names_keeps_requested_failure():
    from app.agent.graph import QueryRun
    from tests.test_agent_loop import make_tools
    run = QueryRun(make_tools(), "查室友的课，再查张三的课", None,
                   credentials=("url", "key", "model"), config={"test": True})
    facts = [
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "王二(软件2401)", "date": "2026-10-12"}),
         "result": {"error": "PERSON_NOT_FOUND", "message": "未找到王二"}},
        {"skill": "query_other_day_courses", "arguments": json.dumps({"person": "张三(软件2402)", "date": "2026-10-12"}),
         "result": {"courses": []}},
    ]
    assert run.other_error(facts)["answer"] == "未找到王二"
    assert not facts[0].get("_superseded")


@pytest.mark.parametrize("key,clear", [(None, False), ("", False), ("   ", False), ("ignored", True)])
def test_endpoint_change_requires_nonempty_effective_key(monkeypatch, key, clear):
    monkeypatch.setattr(llm_config, "get_llm_config", lambda _: {"base_url": "https://old.example", "api_key": "saved-key"})
    monkeypatch.setenv("LLM_ALLOWED_BASE_URLS", "https://new.example")
    with pytest.raises(ValueError, match="explicitly"):
        llm_config.save_llm_config("agent", {"base_url": "https://new.example"}, key, clear)


def test_database_empty_key_cannot_borrow_environment_key(monkeypatch):
    from app.agent import intent_ai, polish_ai
    config = {"source": "database", "base_url": "https://new.example", "api_key": "", "model": "model"}
    monkeypatch.setenv("AGENT_API_KEY", "environment-secret")
    monkeypatch.setattr(intent_ai, "get_llm_config", lambda _: config)
    monkeypatch.setattr(polish_ai, "get_llm_config", lambda _: config)
    assert intent_ai.agent_config() == ("https://new.example", "", "model")
    assert polish_ai.polish_config()[1] == ""


@pytest.mark.parametrize("explicit", [False, True])
def test_all_empty_weeks_cannot_erase_an_entire_term(explicit):
    import httpx

    from tests.test_academic import report, timetable_handler
    def handler(request):
        if request.url.path == "/report/sample":
            return httpx.Response(200, text=report(""))
        if request.url.path.endswith("getXskb"):
            return httpx.Response(200, json={"ret": 0, **({"data": {"kckbData": []}} if explicit else {})})
        return timetable_handler(request)
    with academic.CcsutClient({"Cookie": "test"}, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(academic.AcademicError, match="空课表"):
            client.schedule("student123", "2026-2027-1")


def test_compose_gateway_keeps_distinct_clients_distinct(monkeypatch):
    from dataclasses import replace

    from app import rate_limit
    monkeypatch.setattr(rate_limit, "settings", replace(rate_limit.settings, trust_proxy_headers=True))
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128,172.30.240.1/32")
    def request(ip):
        return Request({"type": "http", "client": ("172.30.240.1", 1234),
                        "headers": [(b"x-forwarded-for", ("1.1.1.1, " + ip).encode())]})
    assert rate_limit.client_ip(request("8.8.8.8")) == "8.8.8.8"
    assert rate_limit.client_ip(request("9.9.9.9")) == "9.9.9.9"
