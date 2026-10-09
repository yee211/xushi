"""Cross-client cache isolation and concurrent stale-fill regression tests."""
from redis.exceptions import RedisError

from app.services import user_cache


class Redis:
    def __init__(self):
        self.values = {}
    def get(self, key):
        return self.values.get(key)
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True


def test_user_cache_is_shared_by_channels_and_isolated_by_account(monkeypatch):
    redis = Redis()
    monkeypatch.setattr(user_cache, "get_redis", lambda: redis)
    data, key = user_cache.read("schedules", 10)
    assert data is None
    user_cache.store(key, [{"id": 123}])
    assert user_cache.read("schedules", 10)[0] == [{"id": 123}]
    assert user_cache.read("schedules", 11)[0] is None


def test_mutation_cannot_be_undone_by_an_old_cache_fill(monkeypatch):
    redis = Redis()
    monkeypatch.setattr(user_cache, "get_redis", lambda: redis)
    _, old_key = user_cache.read("schedules", 10)
    user_cache.invalidate_user(10)
    user_cache.store(old_key, [{"id": "old"}])
    data, new_key = user_cache.read("schedules", 10)
    assert data is None and new_key != old_key
    user_cache.store(new_key, [{"id": "new"}])
    assert user_cache.read("schedules", 10)[0] == [{"id": "new"}]


def test_evicted_generation_never_reuses_an_old_key(monkeypatch):
    redis = Redis()
    monkeypatch.setattr(user_cache, "get_redis", lambda: redis)
    _, old_key = user_cache.read("schedules", 10)
    user_cache.store(old_key, [])
    redis.values.pop(f"{user_cache.PREFIX}10:generation")
    assert user_cache.read("schedules", 10)[1] != old_key


def test_redis_failure_falls_back_without_failing_requests(monkeypatch):
    class Broken:
        def get(self, key):
            raise RedisError("offline")
        def set(self, *args, **kwargs):
            raise RedisError("offline")
    monkeypatch.setattr(user_cache, "get_redis", Broken)
    assert user_cache.read("schedules", 10) == (None, None)
    user_cache.store("key", [])
    user_cache.invalidate_user(10)
