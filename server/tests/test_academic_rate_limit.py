import time

import pytest
from redis.exceptions import ConnectionError

from app.services import academic_rate_limit as limiter
from app.services.academic import AcademicError

# Retain the original function before autouse fixtures disable real waiting.
acquire = limiter.acquire


def test_redis_account_budget_uses_atomic_expiring_slot(monkeypatch):
    class Redis:
        def set(self, key, value, **kwargs):
            assert key == 'xushi:academic:upstream-slot'
            assert kwargs == {'nx': True, 'px': 1000}
            return True
    monkeypatch.setattr(limiter, 'get_redis', lambda: Redis())
    acquire(time.monotonic()+1)


def test_unavailable_redis_does_not_bypass_shared_limit(monkeypatch):
    class Redis:
        def set(self, *args, **kwargs):
            raise ConnectionError('offline')
    monkeypatch.setattr(limiter, 'get_redis', lambda: Redis())
    with pytest.raises(AcademicError) as error:
        acquire(time.monotonic()+1)
    assert error.value.status == 503
