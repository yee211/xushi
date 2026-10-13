"""Shared deadline for model calls and queue waits within one assistant turn."""
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

_deadline = ContextVar("agent_deadline", default=None)


def remaining(default=30.0):
    deadline = _deadline.get()
    value = min(default, deadline - time.monotonic()) if deadline is not None else default
    if value <= 0:
        raise httpx.TimeoutException("Agent turn budget exhausted")
    return value


def available():
    try:
        remaining()
        return True
    except httpx.TimeoutException:
        return False


@contextmanager
def execution():
    if _deadline.get() is not None:
        yield
        return
    seconds = max(3.0, min(float(os.getenv("AGENT_TURN_TIMEOUT_SECONDS", "25")), 90.0))
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)
