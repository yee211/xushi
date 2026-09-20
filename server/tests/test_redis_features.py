"""针对 Redis 统一客户端、Session 鉴权缓存、分布式滑动窗口限流、分享预览缓存及容灾降级的测试。"""
import json
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from app.auth import deps
from app.rate_limit import SlidingWindowLimiter
from app.redis import (
    get_redis,
    redis_delete,
    redis_get,
    redis_set,
    reset_redis_client,
    set_redis_client,
)
from app.services import schedule_share


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []

    def zremrangebyscore(self, name, min_val, max_val):
        self.commands.append(("zremrangebyscore", name, min_val, max_val))
        return self

    def zcard(self, name):
        self.commands.append(("zcard", name))
        return self

    def zrange(self, name, start, end, withscores=False):
        self.commands.append(("zrange", name, start, end, withscores))
        return self

    def zadd(self, name, mapping):
        self.commands.append(("zadd", name, mapping))
        return self

    def expire(self, name, time):
        self.commands.append(("expire", name, time))
        return self

    def execute(self):
        results = []
        for cmd in self.commands:
            name = cmd[0]
            if name == "zremrangebyscore":
                key, min_v, max_v = cmd[1], cmd[2], cmd[3]
                zset = self.client.zsets.setdefault(key, {})
                to_del = [m for m, s in zset.items() if min_v <= s <= max_v]
                for m in to_del:
                    del zset[m]
                results.append(len(to_del))
            elif name == "zcard":
                key = cmd[1]
                results.append(len(self.client.zsets.get(key, {})))
            elif name == "zrange":
                key, start, end, withscores = cmd[1], cmd[2], cmd[3], cmd[4]
                zset = self.client.zsets.get(key, {})
                sorted_items = sorted(zset.items(), key=lambda x: x[1])
                if end == -1 or end >= len(sorted_items):
                    slice_items = sorted_items[start:]
                else:
                    slice_items = sorted_items[start : end + 1]
                if withscores:
                    results.append(slice_items)
                else:
                    results.append([m for m, _ in slice_items])
            elif name == "zadd":
                key, mapping = cmd[1], cmd[2]
                zset = self.client.zsets.setdefault(key, {})
                zset.update(mapping)
                results.append(len(mapping))
            elif name == "expire":
                results.append(True)
        self.commands = []
        return results


class ComprehensiveFakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.zsets = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = str(value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.values:
                del self.values[k]
                count += 1
            if k in self.zsets:
                del self.zsets[k]
                count += 1
        return count

    def pipeline(self):
        return FakePipeline(self)


class BrokenRedis(ComprehensiveFakeRedis):
    """模拟 Redis 抛出网络或服务异常。"""

    def get(self, key):
        raise RedisError("Connection lost to Redis")

    def set(self, key, value, ex=None):
        raise RedisError("Redis read-only replica")

    def delete(self, *keys):
        raise RedisError("Redis timeout")

    def pipeline(self):
        raise RedisError("Pipeline network break")


@pytest.fixture(autouse=True)
def cleanup_redis():
    reset_redis_client()
    yield
    reset_redis_client()


def test_redis_client_safe_degradation_without_config(monkeypatch):
    """未配置或配置为空时，快捷工具函数平滑返回 None/False 而不抛出异常。"""
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("AGENT_REDIS_URL", "")
    assert get_redis() is None
    assert redis_get("non_existent_key") is None
    assert redis_set("some_key", "value") is False
    assert redis_delete("some_key") is False


def test_redis_client_crud_with_injected_client():
    """注入 FakeRedis 客户端后，标准的 get/set/delete 正常工作。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    assert redis_set("xushi:test:foo", "bar", ex=60) is True
    assert redis_get("xushi:test:foo") == "bar"
    assert fake.ttls.get("xushi:test:foo") == 60

    assert redis_delete("xushi:test:foo") is True
    assert redis_get("xushi:test:foo") is None


def test_redis_client_fault_tolerance():
    """当 Redis 客户端抛出 RedisError 时，所有工具函数捕获异常并返回 fallback。"""
    broken = BrokenRedis()
    set_redis_client(broken)

    assert redis_get("any_key") is None
    assert redis_set("any_key", "value") is False
    assert redis_delete("any_key") is False


def test_session_auth_cache_hit_and_invalidation(monkeypatch):
    """测试会话 Token 鉴权：首次查 DB 并回填 Redis，二次直接命中 Redis 内存，失效后重新回源。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    db_query_count = 0
    test_user = {"id": 88, "openid": "wx_openid_test", "email": "test@example.com", "username": "张同学"}

    class MockDB:
        def execute(self, sql, params=None):
            nonlocal db_query_count
            db_query_count += 1
            return self

        def fetchone(self):
            return dict(test_user)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(deps, "connect", lambda: MockDB())

    token = "test_bearer_token_12345"
    digest = deps.token_hash(token)
    cache_key = f"xushi:session:{digest}"

    # 1. 首次鉴权：Redis 未命中，打 DB，写入 Redis
    user1 = deps._user_from_session(token)
    assert user1["id"] == 88
    assert db_query_count == 1
    assert fake.get(cache_key) is not None
    cached_payload = json.loads(fake.get(cache_key))
    assert cached_payload["id"] == 88

    # 2. 第二次鉴权：直接命中 Redis，不打 DB
    user2 = deps._user_from_session(token)
    assert user2["id"] == 88
    assert db_query_count == 1  # 依然是 1，证明没有查库！

    # 3. 淘汰会话缓存
    deps.invalidate_session_cache(token=token)
    assert fake.get(cache_key) is None

    # 4. 第三次鉴权：缓存已被清空，重新查库
    user3 = deps._user_from_session(token)
    assert user3["id"] == 88
    assert db_query_count == 2


def test_session_auth_degrades_when_redis_fails(monkeypatch):
    """当 Redis 故障时，鉴权自动安全降级直查 DB，绝不报 500。"""
    broken = BrokenRedis()
    set_redis_client(broken)

    test_user = {"id": 99, "openid": "wx_failover", "email": "failover@example.com", "username": "李同学"}

    class MockDB:
        def execute(self, sql, params=None):
            return self

        def fetchone(self):
            return dict(test_user)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(deps, "connect", lambda: MockDB())

    user = deps._user_from_session("any_token")
    assert user["id"] == 99


def test_sliding_window_limiter_with_redis():
    """验证基于 Redis ZSET 的分布式滑动窗口限流逻辑。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    limiter = SlidingWindowLimiter(limit=3, window_seconds=10, prefix="test:limiter")

    # 前 3 次请求放行
    for _i in range(3):
        allowed, retry_after = limiter.hit("client_1")
        assert allowed is True
        assert retry_after == 0

    # 第 4 次请求被限流拦截
    allowed, retry_after = limiter.hit("client_1")
    assert allowed is False
    assert retry_after > 0

    # 其他客户端不受影响
    allowed_other, _ = limiter.hit("client_2")
    assert allowed_other is True


def test_sliding_window_limiter_fallback_to_memory_when_redis_broken():
    """验证当 Redis 发生异常时，限流器自动平滑降级为内存限流。"""
    broken = BrokenRedis()
    set_redis_client(broken)

    limiter = SlidingWindowLimiter(limit=2, window_seconds=5, prefix="test:fallback")

    # 第一次放行
    allowed1, _ = limiter.hit("ip_1")
    assert allowed1 is True

    # 第二次放行
    allowed2, _ = limiter.hit("ip_1")
    assert allowed2 is True

    # 第三次拦截（走内存 fallback 成功生效）
    allowed3, retry_after = limiter.hit("ip_1")
    assert allowed3 is False
    assert retry_after >= 1


def test_schedule_share_preview_cache(monkeypatch):
    """验证公开分享课表预览缓存的命中与回填机制。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    mock_row = {
        "code": "AB3456",
        "schedule_id": 10,
        "user_id": 1,
        "expires_at": datetime.now(UTC) + timedelta(days=3),
        "schedule_name": "计算机2024班级课表",
        "term": "2025-2026学年第2学期",
        "start_date": "2026-03-01",
        "end_date": "2026-07-01",
        "username": "班长",
        "email": "monitor@example.com",
    }
    db_calls = 0

    class MockShareDB:
        def execute(self, sql, params=None):
            nonlocal db_calls
            db_calls += 1
            if "COUNT(*)" in sql:
                return MockShareDBResult([{"count": 15}])
            return MockShareDBResult([mock_row])

    class MockShareDBResult:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    # 1. 首次查询：查 DB，回填 Redis
    res1 = schedule_share.get_share_info(MockShareDB(), "AB3456")
    assert res1["name"] == "计算机2024班级课表"
    assert res1["course_count"] == 15
    assert db_calls == 2  # 一次查 share_codes+schedules，一次查课程计数 COUNT(*)
    assert fake.get("xushi:share:preview:AB3456") is not None

    # 2. 第二次查询：命中 Redis 缓存，DB 次数不增加
    res2 = schedule_share.get_share_info(MockShareDB(), "AB3456")
    assert res2["name"] == "计算机2024班级课表"
    assert res2["course_count"] == 15
    assert db_calls == 2  # 保持 2，证明纯读缓存！

    # 3. 淘汰缓存
    schedule_share.invalidate_share_cache("AB3456")
    assert fake.get("xushi:share:preview:AB3456") is None

    # 4. 第三次查询：重新回源查 DB
    schedule_share.get_share_info(MockShareDB(), "AB3456")
    assert db_calls == 4


def test_clawbot_rate_limiting(monkeypatch):
    """验证 ClawBot 接收高频消息时触发限流，快速回复拒绝，不调用大模型。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    from app.rate_limit import clawbot_limiter

    original_limit = clawbot_limiter.limit
    original_window = clawbot_limiter.window
    clawbot_limiter.limit = 2
    clawbot_limiter.window = 10

    try:
        from app.channels.weixin import worker
        from app.channels.weixin.protocol import InboundText

        class DummyDB:
            def execute(self, *args, **kwargs):
                return self

            def fetchone(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(worker, "connect", lambda: DummyDB())

        llm_called = 0

        def fake_build_agent_reply(*args, **kwargs):
            nonlocal llm_called
            llm_called += 1
            return "正常的课表回答"

        monkeypatch.setattr(worker, "build_agent_reply", fake_build_agent_reply)
        monkeypatch.setattr(worker, "claim_message", lambda *args: True)
        monkeypatch.setattr(worker, "complete_message", lambda *args: True)

        sent_replies = []

        class MockILinkClient:
            def send_text(self, sender_id, text, *args, **kwargs):
                sent_replies.append((sender_id, text))

            def send_typing_indicator(self, *args, **kwargs):
                pass

        client = MockILinkClient()
        now = datetime.now(UTC)
        msg1 = InboundText("acc1", "wx_user_1", "msg1", "今天有啥课", "ctx1", now, "run1")
        msg2 = InboundText("acc1", "wx_user_1", "msg2", "明天呢", "ctx1", now, "run1")
        msg3 = InboundText("acc1", "wx_user_1", "msg3", "后天呢", "ctx1", now, "run1")

        # 前两次正常放行并调用大模型
        assert worker.process_message(client, msg1) is True
        assert worker.process_message(client, msg2) is True
        assert llm_called == 2
        assert sent_replies[0][1] == "正常的课表回答"
        assert sent_replies[1][1] == "正常的课表回答"

        # 第三次被限流拦截，直接快速返回提示语，不调用大模型
        assert worker.process_message(client, msg3) is True
        assert llm_called == 2  # 依然是 2，证明完全没调用大模型！
        assert "频繁" in sent_replies[2][1]
    finally:
        clawbot_limiter.limit = original_limit
        clawbot_limiter.window = original_window


def test_wecom_rate_limiting(monkeypatch):
    """验证企业微信机器人接收高频消息时触发限流，快速回复拒绝，不调用大模型。"""
    fake = ComprehensiveFakeRedis()
    set_redis_client(fake)

    from app.channels import wecom
    from app.rate_limit import wecom_limiter

    class DummyDB:
        def execute(self, *args, **kwargs):
            return self

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(wecom, "connect", lambda: DummyDB())

    original_limit = wecom_limiter.limit
    original_window = wecom_limiter.window
    wecom_limiter.limit = 2
    wecom_limiter.window = 10

    try:
        llm_called = 0

        def fake_build_reply(*args, **kwargs):
            nonlocal llm_called
            llm_called += 1
            return "企微回复"

        monkeypatch.setattr(wecom, "build_reply", fake_build_reply)

        posted_replies = []

        def fake_reply_via_response_url(url, content):
            posted_replies.append((url, content))

        monkeypatch.setattr(wecom, "reply_via_response_url", fake_reply_via_response_url)

        # 两次正常放行
        wecom.process_wecom_message("问1", "staff_1", "https://wecom.example.com/resp")
        wecom.process_wecom_message("问2", "staff_1", "https://wecom.example.com/resp")
        assert llm_called == 2

        # 第三次限流拦截
        wecom.process_wecom_message("问3", "staff_1", "https://wecom.example.com/resp")
        assert llm_called == 2  # 不调大模型
        assert "频繁" in posted_replies[2][1]
    finally:
        wecom_limiter.limit = original_limit
        wecom_limiter.window = original_window
