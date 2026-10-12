"""Protocol, time-format and safe-diagnostic regressions."""
import httpx
from test_agent_loop import configure, make_tools, reply_message, tool_call

from app.agent import loop


def test_deepseek_disables_thinking_with_provider_supported_field(monkeypatch):
    sent = configure(monkeypatch, [
        reply_message(tool_calls=[tool_call("c1", "query_day_courses", '{"date":"2026-09-09"}')]),
        reply_message(content="明天 14:00 有高数课。"),
    ])
    monkeypatch.setenv("AGENT_BASE_URL", "https://api.deepseek.com")
    result = loop.run(make_tools(), "明天有什么课")
    assert result is not None
    assert all(request["thinking"] == {"type": "disabled"} for request in sent)
    assert all("enable_thinking" not in request for request in sent)


def test_equivalent_clock_formats_pass_but_new_time_is_rejected():
    assert loop._grounded("今天 8:20 上课", '{"start_time":"08:20"}')
    assert loop._grounded("今天 08:20 上课", '{"start_time":"8:20"}')
    assert not loop._grounded("今天 8:21 上课", '{"start_time":"08:20"}')


def test_provider_failure_logs_status_without_credentials(monkeypatch, caplog):
    configure(monkeypatch, [])
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(400, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("Bad request", request=request, response=response)

    monkeypatch.setattr(loop, "_post_llm", fail)
    assert loop.run(make_tools(), "明天有什么课") is None
    assert "type=HTTPStatusError status=400" in caplog.text
    assert "sk-test" not in caplog.text
