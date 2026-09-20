"""Long-running iLink poller. Run separately from uvicorn."""
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ...agent.service import build_agent_reply
from ...db import close_pool, connect, init_db, init_pool
from ...rate_limit import clawbot_limiter
from .client import ILinkClient, ILinkError, reply_client_id
from .protocol import Credentials, InboundText, extract_text_items
from .store import (
    claim_message,
    complete_message,
    load_accounts,
    reset_stale_processing,
    save_cursor,
)

logger = logging.getLogger("weixin-ilink")
_running = True
SUPERVISOR_INTERVAL_SECONDS = 10

_shared_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_last_push_date: date | None = None


def check_morning_push() -> None:
    global _last_push_date
    if os.getenv("MORNING_PUSH_ENABLED", "true").lower() in ("false", "0", "no"):
        return
    timezone_name = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    now = datetime.now(ZoneInfo(timezone_name))
    today = now.date()
    if _last_push_date == today:
        return
    push_time_str = os.getenv("MORNING_PUSH_TIME", "07:30").strip()
    try:
        parts = push_time_str.split(":")
        push_hour, push_minute = int(parts[0]), int(parts[1])
    except Exception:
        push_hour, push_minute = 7, 30

    if (now.hour, now.minute) < (push_hour, push_minute):
        return

    try:
        with connect() as db:
            from ...services.daily_push import dispatch_morning_pushes, pending_morning_push_count
            sent = dispatch_morning_pushes(db, today, timezone_name)
            if sent > 0:
                logger.info("morning push dispatched: %s sent for %s", sent, today)
            pending = pending_morning_push_count(db, today)
        if pending == 0:
            _last_push_date = today
        else:
            logger.warning("morning push still has %s pending recipient(s) for %s; will retry", pending, today)
    except Exception:
        logger.exception("failed to dispatch morning push")


def worker_concurrency() -> int:
    return max(2, min(int(os.getenv("WEIXIN_WORKER_CONCURRENCY", "16")), 128))


def get_executor() -> ThreadPoolExecutor:
    global _shared_executor
    if _shared_executor is None:
        with _executor_lock:
            if _shared_executor is None:
                _shared_executor = ThreadPoolExecutor(
                    max_workers=worker_concurrency(),
                    thread_name_prefix="ilink-msg-",
                )
    return _shared_executor


def shutdown_executor(wait: bool = True) -> None:
    global _shared_executor
    with _executor_lock:
        if _shared_executor is not None:
            _shared_executor.shutdown(wait=wait, cancel_futures=False)
            _shared_executor = None


def _stop(*_args) -> None:
    global _running
    _running = False


def _wait(seconds: int) -> None:
    """Back off while still reacting promptly to SIGTERM."""
    deadline = time.monotonic() + seconds
    while _running and time.monotonic() < deadline:
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def _received_at(raw: dict) -> datetime:
    milliseconds = int(raw.get("create_time_ms") or 0)
    timezone = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))
    if milliseconds > 0:
        return datetime.fromtimestamp(milliseconds / 1000, UTC).astimezone(timezone)
    return datetime.now(timezone)


def process_message(client: ILinkClient, message: InboundText) -> bool:
    with connect() as db:
        if not claim_message(db, message.account_id, message.message_id):
            return True
        if message.context_token:
            db.execute("""UPDATE user_identities SET last_seen_at=CURRENT_TIMESTAMP, context_token=%s
                WHERE provider='weixin_ilink' AND provider_user_id=%s""",
                (message.context_token, message.sender_id))
    try:
        allowed, retry_after = clawbot_limiter.hit(message.sender_id)
        if not allowed:
            reply = f"你提问太频繁啦，请慢一点~ 请等待 {retry_after} 秒后再问我吧。"
            client.send_text(message.sender_id, reply, message.context_token,
                             client_id=reply_client_id(message.account_id, message.message_id),
                             run_id=message.run_id)
            with connect() as db:
                complete_message(db, message.account_id, message.message_id)
            logger.warning("clawbot rate limited sender=%s account=%s", message.sender_id, message.account_id)
            return True

        if client:
            threading.Thread(
                target=client.send_typing_indicator,
                args=(message.sender_id, message.context_token),
                kwargs={"status": 1},
                daemon=True,
                name=f"typing-{message.message_id[:8]}",
            ).start()
        with connect() as db:
            reply = build_agent_reply(db, message.text, "weixin_ilink", message.sender_id,
                                      message.received_at, os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
                                      message.account_id)
        client.send_text(message.sender_id, reply, message.context_token,
                         client_id=reply_client_id(message.account_id, message.message_id),
                         run_id=message.run_id)
        with connect() as db:
            complete_message(db, message.account_id, message.message_id)
        logger.info("replied account=%s message=%s", message.account_id, message.message_id)
        return True
    except Exception as error:
        with connect() as db:
            complete_message(db, message.account_id, message.message_id, str(error))
        logger.exception("message failed account=%s message=%s", message.account_id, message.message_id)
        return False


def process_batch_messages(client: ILinkClient, messages: list[InboundText],
                           executor: ThreadPoolExecutor | None = None) -> bool:
    """并发处理批次消息：不同用户并行无阻塞；同用户按顺序串行执行保会话时序。"""
    if not messages:
        return True
    pool = executor or get_executor()
    groups: dict[str, list[InboundText]] = {}
    for message in messages:
        groups.setdefault(message.sender_id, []).append(message)

    def _process_user_group(user_messages: list[InboundText]) -> bool:
        group_ok = True
        for msg in user_messages:
            if not process_message(client, msg):
                group_ok = False
        return group_ok

    if len(groups) == 1 and (executor is None and pool is None):
        return _process_user_group(messages)

    futures = [pool.submit(_process_user_group, msgs) for msgs in groups.values()]
    all_ok = True
    for future in futures:
        try:
            if not future.result():
                all_ok = False
        except Exception:
            logger.exception("unexpected error in message worker thread")
            all_ok = False
    return all_ok


def poll_account(credentials: Credentials, cursor: str, stop_event: threading.Event | None = None,
                 executor: ThreadPoolExecutor | None = None) -> str:
    stop_event = stop_event or threading.Event()
    client = ILinkClient(credentials)
    try:
        try:
            client.notify(True)
        except Exception:
            logger.warning("failed to send start notification", exc_info=True)
        while _running and not stop_event.is_set():
            try:
                result = client.get_updates(cursor)
                inbound_msgs = []
                for raw in result.get("msgs") or []:
                    message = extract_text_items(raw, credentials.account_id, _received_at(raw))
                    if message:
                        inbound_msgs.append(message)
                if inbound_msgs:
                    ok = process_batch_messages(client, inbound_msgs, executor)
                    if not ok:
                        stop_event.wait(3)
                        continue
                next_cursor = str(result.get("get_updates_buf") or "")
                if next_cursor and next_cursor != cursor:
                    cursor = next_cursor
                    with connect() as db:
                        save_cursor(db, credentials.account_id, cursor)
            except ILinkError as error:
                delay = 3600 if "-14" in str(error) else 10
                logger.warning("poll failed account=%s retry=%ss: %s", credentials.account_id, delay, error)
                stop_event.wait(delay)
            except Exception:
                logger.exception("unexpected poll error account=%s", credentials.account_id)
                stop_event.wait(5)
    finally:
        try:
            client.notify(False)
        except Exception:
            logger.warning("failed to send stop notification", exc_info=True)
        client.close()
    return cursor


def _spawn_poller(credentials: Credentials, cursor: str, stop_event: threading.Event) -> threading.Thread:
    return threading.Thread(target=poll_account, args=(credentials, cursor, stop_event), daemon=True,
                            name=f"ilink-{credentials.account_id[:12]}")


def reconcile_threads(threads: dict[str, tuple[threading.Thread, threading.Event, str]],
                      accounts: list[tuple[Credentials, str, str]],
                      spawn=None) -> None:
    """对齐轮询线程与库内账号：账号删除→停线程；token 轮换→停旧线程等下轮重启；缺失→启动新线程。"""
    spawn = spawn or _spawn_poller
    active_ids = {credentials.account_id for credentials, _, _ in accounts}
    for account_id, (thread, stop_event, _) in list(threads.items()):
        if account_id not in active_ids:
            stop_event.set()
        if not thread.is_alive():
            threads.pop(account_id, None)
    for credentials, cursor, fingerprint in accounts:
        current = threads.get(credentials.account_id)
        if current and current[0].is_alive():
            if current[2] != fingerprint:  # 重新扫码换了 bot_token，旧线程必须停止换新
                logger.info("token rotated, restarting poller account=%s", credentials.account_id)
                current[1].set()
            continue
        threads.pop(credentials.account_id, None)
        stop_event = threading.Event()
        thread = spawn(credentials, cursor, stop_event)
        thread.start()
        threads[credentials.account_id] = (thread, stop_event, fingerprint)
        logger.info("started poller account=%s", credentials.account_id)


def run() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    init_pool()
    init_db()
    with connect() as db:
        reset = reset_stale_processing(db)
    if reset:
        logger.info("reset %s stale processing message(s) left by previous run", reset)
    threads: dict[str, tuple[threading.Thread, threading.Event, str]] = {}
    while _running:
        with connect() as db:
            accounts = load_accounts(db)
        reconcile_threads(threads, accounts)
        check_morning_push()
        _wait(SUPERVISOR_INTERVAL_SECONDS)
    for thread, stop_event, _ in threads.values():
        stop_event.set()
        thread.join(timeout=45)
    shutdown_executor(wait=True)
    close_pool()
