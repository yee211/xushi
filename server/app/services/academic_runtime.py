"""Cooperative job budget with cancellation of active PostgreSQL statements."""
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg.errors import LockNotAvailable, QueryCanceled
from psycopg.pq import TransactionStatus

_current = ContextVar("school_sync_budget", default=None)


class SyncTimeout(Exception):
    pass


class Budget:
    def __init__(self, seconds, progress=None):
        self.deadline = time.monotonic() + seconds
        self.progress = progress

    def remaining(self):
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise SyncTimeout("同步执行超时，原课表已保留，请稍后重试")
        return value


@contextmanager
def execution(seconds, progress=None):
    token = _current.set(Budget(seconds, progress))
    try:
        yield
    finally:
        _current.reset(token)


def remaining(default):
    budget = _current.get()
    return min(default, budget.remaining()) if budget else default


def check():
    remaining(float("inf"))


def stage(value):
    check()
    budget = _current.get()
    if budget and budget.progress:
        budget.progress(value)


@contextmanager
def transaction(db):
    budget = _current.get()
    if not budget:
        yield
        return
    seconds = budget.remaining()
    # A cancelled statement aborts the transaction; the outer connect rolls it back.
    timed_out = threading.Event()

    def committed():
        return getattr(getattr(db, "info", None), "transaction_status", None) == TransactionStatus.IDLE

    def cancel():
        if committed():
            return
        timed_out.set()
        try:
            if hasattr(db, "cancel_safe"):
                db.cancel_safe(timeout=2)
            else:
                db.cancel()
        except Exception as error:
            logging.getLogger(__name__).warning("School SQL cancellation unavailable: %s", type(error).__name__)

    timer = threading.Timer(seconds, cancel)
    timer.daemon = True
    timer.start()
    completed = False
    try:
        db.execute("SELECT set_config('statement_timeout',%s,true)", (str(max(1, int(seconds * 1000))),))
        db.execute("SELECT set_config('lock_timeout',%s,true)", (str(max(1, int(min(15, seconds) * 1000))),))
        yield
        if not committed():
            check()
        completed = True
    except (LockNotAvailable, QueryCanceled) as error:
        raise SyncTimeout('同步数据库等待超时，原课表已保留，请稍后重试') from error
    finally:
        timer.cancel()
        timer.join()
        if completed and timed_out.is_set() and not committed():
            raise SyncTimeout("同步执行超时，原课表已保留，请稍后重试")
