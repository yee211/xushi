"""Bounded, best-effort metrics writer isolated from HTTP request latency."""
import logging
import queue
import threading
import time

from ..db import connect
from .user_activity import touch

logger = logging.getLogger(__name__)
_pending = queue.Queue(maxsize=1000)
_stop = threading.Event()
_thread = None


def enqueue(method, path, status, duration, user_id=None):
    try:
        _pending.put_nowait((method, path[:250], status, duration, user_id))
    except queue.Full:
        pass


def _worker():
    next_cleanup = 0
    while not _stop.is_set():
        try:
            metric = _pending.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            with connect() as db:
                db.execute("INSERT INTO api_request_logs(method,path,status,duration_ms) VALUES(%s,%s,%s,%s)", metric[:4])
                if metric[4] is not None and 200 <= metric[2] < 400:
                    touch(db, metric[4])
                if time.monotonic() >= next_cleanup:
                    db.execute("DELETE FROM api_request_logs WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'")
                    next_cleanup = time.monotonic() + 3600
        except Exception:
            logger.warning("Request metrics write failed", exc_info=True)
            _stop.wait(5)
        finally:
            _pending.task_done()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker, name="request-metrics", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
