"""Bounded, best-effort agent turn metrics writer, mirroring request_metrics.

每轮 agent 处理结束时由 orchestrator 入队，后台线程落库 agent_turn_logs，
保留 7 天，供管理后台「助手运行」面板聚合展示。写入失败只告警、不影响回复。
"""
import logging
import queue
import threading
import time

from ..db import connect

logger = logging.getLogger(__name__)
_pending = queue.Queue(maxsize=1000)
_stop = threading.Event()
_thread = None

RETENTION_DAYS = 7


def enqueue(turn: dict) -> None:
    """入队一轮 agent_turn 指标；队列满时静默丢弃（指标可丢，回复不可断）。"""
    try:
        _pending.put_nowait((
            str(turn.get("path") or "unknown")[:16],
            str(turn.get("outcome") or "ok")[:24],
            int(turn.get("rounds") or 0),
            int(turn.get("llm_calls") or 0),
            int(turn.get("prompt_tokens") or 0),
            int(turn.get("completion_tokens") or 0),
            int(turn.get("cached_tokens") or 0),
            float(turn.get("duration_ms") or 0),
            str(turn.get("breaker") or "")[:16],
        ))
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
                db.execute("""INSERT INTO agent_turn_logs(path,outcome,rounds,llm_calls,
                    prompt_tokens,completion_tokens,cached_tokens,duration_ms,breaker)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", metric)
                if time.monotonic() >= next_cleanup:
                    db.execute(
                        "DELETE FROM agent_turn_logs WHERE created_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')",
                        (RETENTION_DAYS,))
                    next_cleanup = time.monotonic() + 3600
        except Exception:
            logger.warning("Agent metrics write failed", exc_info=True)
            _stop.wait(5)
        finally:
            _pending.task_done()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker, name="agent-metrics", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
