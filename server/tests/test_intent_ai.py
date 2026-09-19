"""LLM 结构化意图兜底（intent_ai）测试：全部 mock httpx，不发起真实请求。"""
import json
import sys
from datetime import date
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import intent_ai  # noqa: E402

TODAY = date(2026, 9, 8)


class FakeResponse:
    def __init__(self, content): self._content = content

    def raise_for_status(self): pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def configure(monkeypatch, content, raises=None):
    monkeypatch.setenv("AGENT_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("AGENT_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MODEL", "test-model")

    def fake_post(url, **kwargs):
        if raises:
            raise raises("network down")
        return FakeResponse(content)

    monkeypatch.setattr(intent_ai.httpx, "post", fake_post)


def test_extract_intent_parses_plain_json(monkeypatch):
    payload = {"intent": "QUERY_DAY", "date": "2026-09-09", "period": "afternoon",
               "weekday": None, "course_name": ""}
    configure(monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = intent_ai.extract_intent("明天下午有什么课", TODAY)
    assert result == {"name": "QUERY_DAY", "target_date": "2026-09-09", "period": "afternoon",
                      "weekday": None, "course_name": ""}


def test_extract_intent_injects_server_received_time(monkeypatch):
    captured = {}
    payload = {"intent": "QUERY_DAY", "date": "2026-09-14", "period": "all",
               "weekday": None, "course_name": ""}

    def fake_post(url, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse(json.dumps(payload, ensure_ascii=False))

    configure(monkeypatch, json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(intent_ai.httpx, "post", fake_post)
    intent_ai.extract_intent("明天有什么课", date(2026, 9, 13),
                             received_at="2026-09-13T23:58:40+08:00")
    prompt = captured["messages"][-1]["content"]
    assert "2026-09-13T23:58:40+08:00" in prompt and "Asia/Shanghai" in prompt


def test_extract_intent_limits_course_rewrite_to_user_catalog(monkeypatch):
    payload = {"intent": "FIND_COURSE", "date": "", "period": "all", "weekday": None,
               "course_name": "计算机组成原理"}
    configure(monkeypatch, json.dumps(payload, ensure_ascii=False))
    catalog = [{"course_id": 12, "name": "计算机组成原理"}]
    result = intent_ai.extract_intent("计组什么时候上", TODAY, course_catalog=catalog)
    assert result["course_name"] == "计算机组成原理"

    payload["course_name"] = "不存在的课程"
    configure(monkeypatch, json.dumps(payload, ensure_ascii=False))
    assert intent_ai.extract_intent("计组什么时候上", TODAY, course_catalog=catalog) is None


def test_extract_intent_injects_new_short_history_with_valid_roles(monkeypatch):
    captured = {}
    payload = {"intent": "QUERY_DAY", "date": "2026-09-09", "period": "morning",
               "weekday": None, "course_name": ""}

    def fake_post(url, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse(json.dumps(payload, ensure_ascii=False))

    configure(monkeypatch, json.dumps(payload))
    monkeypatch.setattr(intent_ai.httpx, "post", fake_post)
    history = [HumanMessage(content="明天下午有什么课"), AIMessage(content="有两门课")]
    intent_ai.extract_intent("那上午呢", TODAY, history=history)
    roles = [item["role"] for item in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_extract_intent_parses_code_fence(monkeypatch):
    payload = {"intent": "FIND_COURSE", "date": "", "period": "all", "weekday": None, "course_name": "高数"}
    configure(monkeypatch, "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
    result = intent_ai.extract_intent("高数什么时候上", TODAY)
    assert result["name"] == "FIND_COURSE" and result["course_name"] == "高数"


def test_extract_intent_rejects_disallowed_intent_and_period(monkeypatch):
    bad = {"intent": "DELETE_SCHEDULE", "date": "", "period": "all", "weekday": None, "course_name": ""}
    configure(monkeypatch, json.dumps(bad))
    assert intent_ai.extract_intent("删掉课表", TODAY) is None
    bad_period = {**bad, "intent": "QUERY_DAY", "period": "midnight"}
    configure(monkeypatch, json.dumps(bad_period))
    assert intent_ai.extract_intent("今天有课吗", TODAY) is None


def test_extract_intent_rejects_invalid_date_and_weekday(monkeypatch):
    configure(monkeypatch, json.dumps({"intent": "QUERY_DAY", "date": "not-a-date", "period": "all",
                                       "weekday": None, "course_name": ""}))
    assert intent_ai.extract_intent("今天有什么课", TODAY) is None


def test_extract_intent_rejects_missing_required_query_fields(monkeypatch):
    configure(monkeypatch, json.dumps({"intent": "QUERY_DAY", "date": "", "period": "all",
                                       "weekday": None, "course_name": ""}))
    assert intent_ai.extract_intent("今天有什么课", TODAY) is None
    configure(monkeypatch, json.dumps({"intent": "FIND_COURSE", "date": "", "period": "all",
                                       "weekday": None, "course_name": ""}))
    assert intent_ai.extract_intent("计组什么时候上", TODAY) is None
    configure(monkeypatch, json.dumps({"intent": "QUERY_DAY", "date": "", "period": "all",
                                       "weekday": 9, "course_name": ""}))
    assert intent_ai.extract_intent("今天有什么课", TODAY) is None
    configure(monkeypatch, json.dumps({"intent": "QUERY_WEATHER", "date": "", "period": "all",
                                       "weekday": None, "course_name": ""}))
    assert intent_ai.extract_intent("明天要带伞吗", TODAY) is None


def test_extract_intent_accepts_course_presence_with_raw_name(monkeypatch):
    # “明天有机组课吗”里课程字样允许不在候选中（照抄用户原词），但日期与课程名缺一不可
    catalog = [{"course_id": 3, "name": "计算机网络"}]
    payload = {"intent": "QUERY_COURSE_ON_DAY", "date": "2026-09-09", "period": "all",
               "weekday": None, "course_name": "机组课"}
    configure(monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = intent_ai.extract_intent("明天有机组课吗", TODAY, course_catalog=catalog)
    assert result == {"name": "QUERY_COURSE_ON_DAY", "target_date": "2026-09-09", "period": "all",
                      "weekday": None, "course_name": "机组课"}
    configure(monkeypatch, json.dumps({**payload, "date": ""}, ensure_ascii=False))
    assert intent_ai.extract_intent("明天有机组课吗", TODAY, course_catalog=catalog) is None
    configure(monkeypatch, json.dumps({**payload, "course_name": ""}, ensure_ascii=False))
    assert intent_ai.extract_intent("明天有机组课吗", TODAY, course_catalog=catalog) is None


def test_extract_intent_tolerates_network_and_parse_errors(monkeypatch):
    configure(monkeypatch, "不是 JSON", raises=None)
    assert intent_ai.extract_intent("随便", TODAY) is None
    import httpx as httpx_module
    configure(monkeypatch, "", raises=httpx_module.ConnectError)
    assert intent_ai.extract_intent("随便", TODAY) is None


def test_extract_intent_returns_none_when_unconfigured(monkeypatch):
    # AGENT_* 未配置时还会回退读取 AI_*，测试必须两者都清空，避免读到本机 .env 发起真实请求
    for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL",
                 "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert intent_ai.extract_intent("明天有什么课", TODAY) is None
