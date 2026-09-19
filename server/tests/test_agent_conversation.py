import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent import conversation


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key], self.ttls[key] = value, ttl


def test_redis_history_is_versioned_user_scoped_and_trimmed(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(conversation, "_client", lambda: redis)
    now = datetime(2026, 9, 13, 23, 58, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    for index in range(6):
        conversation.append_turn(7, "wecom", "zhangsan", f"问题{index}", f"回答{index}", now,
                                 {"intent": "QUERY_DAY", "target_date": "2026-09-14"})

    key = conversation._key(7, "wecom", "zhangsan")
    payload = json.loads(redis.values[key])
    assert ":v2:" in key and len(payload["messages"]) == 12
    assert payload["updated_at"] == now.isoformat()
    assert payload["state"]["target_date"] == "2026-09-14"
    assert redis.ttls[key] == 7200
    assert redis.get(conversation._key(8, "wecom", "zhangsan")) is None

    history = conversation.load_history(7, "wecom", "zhangsan")
    assert len(history) == 12
    # Assistant message must remain completely clean of metadata
    assert history[-1].content == "回答5"
    # User message contains context suffix for relative date parsing
    assert "2026-09-14" in history[-2].content


def test_dirty_history_metadata_is_cleaned_on_load(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(conversation, "_client", lambda: redis)
    now = datetime(2026, 9, 14, 18, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    dirty_reply = ("不是冷漠，我都在\n"
                   "[消息时间: 2026-09-14T18:40:35.315000+08:00; 已解析上下文: {\"intent\": \"AGENT_LOOP\", \"skills\": []}]")
    conversation.append_turn(10, "wecom", "testuser", "你好冷漠", dirty_reply, now, {"intent": "AGENT_LOOP"})

    history = conversation.load_history(10, "wecom", "testuser")
    assert len(history) == 2
    assert history[-1].content == "不是冷漠，我都在"


def test_unconfigured_redis_degrades_to_empty_history(monkeypatch):
    monkeypatch.setattr(conversation, "_client", lambda: None)
    assert conversation.load_history(7, "wecom", "zhangsan") == []
