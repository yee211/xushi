"""Offline clarification flows: real service/graph, simulated persistence/providers."""

# ruff: noqa: F811 -- imported pytest fixtures are referenced by test parameters
import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from redis.exceptions import RedisError

from app.agent import clarification, conversation, orchestrator, service
from tests.fakes import FakeAgentDb, FakeResult
from tests.test_agent_conversation import FakeRedis
from tests.test_agent_graph import isolated_engine, replay  # noqa: F401
from tests.test_agent_loop import reply_message
from tests.test_agent_sync_multiturn import flow  # noqa: F401


def question(text="你想查本周一还是下周一？"):
    return reply_message(
        content=json.dumps({"status": "needs_input", "answer": text, "task_id": None}, ensure_ascii=False)
    )


def test_graph_can_ask_for_date_without_querying_or_waiting(monkeypatch):
    result, requests, _ = replay(monkeypatch, "周一有什么课", [question()])
    assert result["_completion_status"] == "needs_input"
    assert result["answer"] == "你想查本周一还是下周一？"
    assert len(requests) == 1 and result["skills"] == []


def test_clarification_cannot_smuggle_unverified_course_claims(monkeypatch):
    result, _, _ = replay(
        monkeypatch, "明天有什么课", [question("明天没有课，你想查哪一天？"), question("明天没有课，你想查哪一天？")]
    )
    assert result is None


def test_date_answer_resumes_original_request_even_without_model(flow, monkeypatch):
    db, redis, responses, requests, client, finish, say = flow
    responses.append(question())
    assert "本周一还是下周一" in say("周一有什么课")
    pending = clarification.load(
        (7, "weixin_ilink", "sender", "bot"),
        service.ScheduleTools(lambda: db, MagicMock(user_id=7)).schedule_version(),
        datetime(2026, 10, 14, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert pending.original == "周一有什么课"
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    answer = say("下周一")
    assert "10月19日" in answer and "可以问我" not in answer
    assert not redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))
    assert len(requests) == 1


def test_free_text_answer_retains_question_and_original(flow):
    db, redis, responses, requests, client, finish, say = flow
    responses.append(question("你指的是哪一门课程？"))
    assert "哪一门" in say("这门课在哪上")
    responses.append(question("你想查这门课的哪一天？"))
    assert "哪一天" in say("高等数学")
    messages = json.dumps(requests[-1]["messages"], ensure_ascii=False)
    assert "这门课在哪上" in messages and "你指的是哪一门课程" in messages and "高等数学" in messages
    pending = json.loads(redis.get(clarification.key(7, "weixin_ilink", "sender", "bot")))
    assert pending["original"] == "这门课在哪上" and pending["turns"] == [["你指的是哪一门课程？", "高等数学"]]


def test_cancel_clears_question_and_it_does_not_revive_from_history(flow):
    db, redis, responses, requests, client, finish, say = flow
    responses.append(question())
    say("周一有什么课")
    assert "已取消" in say("取消")
    assert not redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))
    responses.append(reply_message(content="在的，可以帮你查课表"))
    say("你好")
    assert "本周一还是下周一" not in json.dumps(requests[-1]["messages"], ensure_ascii=False)


def test_new_request_abandons_question(flow):
    db, redis, responses, requests, client, finish, say = flow
    responses.append(question())
    say("周一有什么课")
    assert "已提交" in say("同步课表")
    assert db.submissions == 1 and len(requests) == 1
    assert not redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))


@pytest.fixture
def choices(monkeypatch):
    schedules = [
        {
            "id": 11,
            "name": "手工课表",
            "term": "2026-2027-1",
            "start_date": date(2026, 8, 1),
            "end_date": date(2027, 1, 1),
            "variant_type": "original",
            "source_schedule_id": None,
        },
        {
            "id": 22,
            "name": "另一张课表",
            "term": "2026-2027-1",
            "start_date": date(2026, 8, 1),
            "end_date": date(2027, 1, 1),
            "variant_type": "original",
            "source_schedule_id": None,
        },
    ]

    class Db(FakeAgentDb):
        revision = 1

        def execute(self, sql, params=None):
            if "AS snapshot" in sql:
                return FakeResult([{"snapshot": {"schedules": self.schedules, "binding_revision": self.revision}}])
            if "SELECT id,name FROM schedules" in sql:
                assert params[1] == 7
                return FakeResult([s for s in self.schedules if s["id"] == params[0]])
            if "FROM courses" in sql:
                return FakeResult([c for c in self.courses if c["schedule_id"] == params[0]])
            return super().execute(sql, params)

    courses = [
        {
            "id": 1,
            "schedule_id": 11,
            "name": "高数",
            "weekday": 3,
            "start_section": 1,
            "end_section": 2,
            "weeks": list(range(1, 31)),
            "teacher": "甲",
            "room": "A101",
        },
        {
            "id": 2,
            "schedule_id": 22,
            "name": "大学英语",
            "weekday": 3,
            "start_section": 1,
            "end_section": 2,
            "weeks": list(range(1, 31)),
            "teacher": "乙",
            "room": "B202",
        },
    ]
    db = Db(identity_user_id=7, schedules=schedules, courses=courses)
    redis = FakeRedis()
    monkeypatch.setattr(conversation, "_client", lambda: redis)
    monkeypatch.setattr(orchestrator, "llm_configured", lambda: False)
    monkeypatch.setattr(orchestrator, "rain_advisory", lambda *args: None)
    now = datetime(2026, 9, 8, 13, tzinfo=ZoneInfo("Asia/Shanghai"))

    def say(text, account="bot", at=None):
        return service.build_agent_reply(
            lambda: db, text, "weixin_ilink", "sender", at or now, account_id=account, message_id="message"
        )

    return db, redis, now, say


@pytest.mark.parametrize("answer", ["第二个", "第2张", "使用课表 22", "另一张课表"])
def test_choose_schedule_and_continue_query_without_model(choices, answer):
    db, redis, now, say = choices
    assert "多张" in say("明天有什么课")
    text = say(answer)
    assert "大学英语" in text and "B202" in text and "高数" not in text
    assert not redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))


def test_invalid_choice_does_not_guess_or_query(choices):
    db, redis, now, say = choices
    say("明天有什么课")
    assert "第几个" in say("第九个")
    assert redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))


@pytest.mark.parametrize("mutation", ["role", "expired", "account"])
def test_stale_or_other_account_question_is_not_resumed(choices, monkeypatch, mutation):
    db, redis, now, say = choices
    say("明天有什么课")
    if mutation == "role":
        db.revision += 1
    seen = []

    def handle(text, tools, history=None):
        seen.append((text, history, tools.context.default_schedule_id))
        return {"answer": "请重新说明要查询的日期。", "status": "completed"}

    monkeypatch.setattr(service, "handle_message", handle)
    say(
        "第二个",
        account="other-bot" if mutation == "account" else "bot",
        at=now + timedelta(minutes=16) if mutation == "expired" else now,
    )
    assert seen[0][0] == "第二个" and seen[0][2] is None
    assert not seen[0][1]


def test_explicit_choice_cannot_access_another_users_schedule(choices):
    db, redis, now, say = choices
    say("明天有什么课")
    assert "没有找到" in say("使用课表 999")
    assert redis.get(clarification.key(7, "weixin_ilink", "sender", "bot"))


def test_redis_write_failure_explains_how_to_continue(choices, monkeypatch):
    db, redis, now, say = choices

    def fail(*args):
        raise RedisError("unavailable")

    monkeypatch.setattr(redis, "setex", fail)
    assert "补充信息与原问题一起发送" in say("明天有什么课")


def test_pending_scope_has_no_sanitization_collisions():
    assert clarification.key(7, "weixin_ilink", "a:b", "bot") != clarification.key(7, "weixin_ilink", "ab", "bot")
    assert clarification.key(7, "weixin_ilink", "sender", "bot") != clarification.key(
        8, "weixin_ilink", "sender", "bot"
    )
