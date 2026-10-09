"""A shared one-request-per-second budget for the school's single account."""
import threading
import time
import uuid

from redis.exceptions import RedisError

from ..redis import get_redis

_lock = threading.Lock()
_next = 0.0


def acquire(deadline):
    global _next
    from .academic import AcademicError
    interactive = threading.current_thread().name == "AnyIO worker thread"
    deadline = min(deadline, time.monotonic() + 2) if interactive else deadline
    client = get_redis()
    if client is not None:
        while time.monotonic() < deadline:
            try:
                if client.set('xushi:academic:upstream-slot', uuid.uuid4().hex, nx=True, px=1000):
                    return
            except RedisError as error:
                raise AcademicError('rate_limit_unavailable', '同步限流暂不可用，请稍后重试', 503) from error
            time.sleep(min(0.1, max(0, deadline-time.monotonic())))
    else:
        with _lock:
            wait = max(0, _next-time.monotonic())
            if time.monotonic()+wait < deadline:
                time.sleep(wait)
                _next = time.monotonic()+1
                return
    raise AcademicError('upstream_timeout', '学校查询排队超时，请稍后重试', 504)
