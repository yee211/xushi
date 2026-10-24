"""清理长期未活跃的“裸 openid”用户（小程序静默登录残留，无任何绑定与数据）。

判定条件（全部满足才删除）：
- 有 openid 且无邮箱、无用户名（即从未注册过账号）；
- 无助手渠道绑定、无教务绑定、无课表、无反馈（不含任何用户数据）；
- 不存在未过期会话（小程序缓存 token 可直接复用的用户不算过期，见 sessions.expires_at）；
- 超过保留期未登录（last_login_at 仅在 /api/auth/wechat 刷新，但缓存 token 期间
  请求全部 401 失败前不会重登，故保留期可以短于 SESSION_DAYS）。

删除前先收集其会话并失效 Redis 会话缓存；所有关联表对 users 均为
ON DELETE CASCADE/SET NULL，直接删用户行即可级联清理。
保留期由 UNBOUND_USER_RETENTION_DAYS 控制（默认 30 天，设为 0 关闭自动清理）。
"""
import logging
import os
import threading

from ..db import connect

logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None
_RUN_INTERVAL_SECONDS = 24 * 3600
_FIRST_RUN_DELAY_SECONDS = 300

# “有绑定身份”的统一判定（admin 后台与清理任务共用，防止口径漂移）：
# 注册过邮箱、绑定了助手渠道或教务学生账号。小程序静默登录只写一条裸 openid 用户行。
BOUND_USER_FILTER = """(
    (u.email IS NOT NULL AND u.email <> '')
    OR EXISTS (SELECT 1 FROM user_identities ui WHERE ui.user_id = u.id)
    OR EXISTS (SELECT 1 FROM academic_bindings ab WHERE ab.user_id = u.id)
)"""

# 可删的“惰性”用户：比绑定口径更严格 —— 连课表、反馈、未过期会话都没有。
INERT_USER_SQL = f"""u.openid IS NOT NULL
    AND u.username IS NULL
    AND NOT {BOUND_USER_FILTER}
    AND NOT EXISTS (SELECT 1 FROM schedules s WHERE s.user_id = u.id)
    AND NOT EXISTS (SELECT 1 FROM feedbacks f WHERE f.user_id = u.id)
    AND NOT EXISTS (SELECT 1 FROM sessions se WHERE se.user_id = u.id AND se.expires_at > CURRENT_TIMESTAMP)
    AND u.last_login_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"""


def retention_days() -> int:
    try:
        return max(0, int(os.getenv("UNBOUND_USER_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def cleanup() -> int:
    """删除过期的裸 openid 用户，返回删除数量；保留期为 0 时直接跳过。"""
    days = retention_days()
    if days <= 0:
        return 0
    with connect() as db:
        digests = db.execute(f"""
            SELECT s.token_hash FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE {INERT_USER_SQL}""", (days,)).fetchall()
        doomed = db.execute(f"""
            WITH doomed AS (SELECT u.id FROM users u WHERE {INERT_USER_SQL})
            DELETE FROM users WHERE id IN (SELECT id FROM doomed) RETURNING id""", (days,)).fetchall()
    if doomed and digests:
        from ..auth.deps import invalidate_session_cache
        for row in digests:
            invalidate_session_cache(token_digest=row["token_hash"])
    return len(doomed)


def _loop():
    # 首轮延迟几分钟，避开应用启动高峰；此后每天巡检一次。
    if _stop.wait(_FIRST_RUN_DELAY_SECONDS):
        return
    while not _stop.is_set():
        try:
            deleted = cleanup()
            if deleted:
                logger.info("Cleaned %d inert unbound users (retention=%dd)", deleted, retention_days())
        except Exception:
            logger.warning("Unbound user cleanup failed", exc_info=True)
        _stop.wait(_RUN_INTERVAL_SECONDS)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="user-cleanup", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
