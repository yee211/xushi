"""进程内滑动窗口限流。

SlidingWindowLimiter 是通用实现（微信登录/反馈/管理后台登录使用）；
enforce_auth_rate_limit 在其上封装邮箱注册登录的限制规则，限额来自
settings（网页母版的 AUTH_RATE_LIMIT / AUTH_RATE_WINDOW_SECONDS），
并支持 TRUST_PROXY_HEADERS 场景下从 X-Forwarded-For 取真实来源。
多实例部署时需替换为 Redis 共享实现。
"""
import logging
import threading
import time
import uuid

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from .redis import get_redis
from .settings import settings

logger = logging.getLogger("classschedule.ratelimit")


class SlidingWindowLimiter:
    """滑动窗口限流器。

    支持 Redis 分布式共享限流（基于 ZSET）；未配置 Redis 或发生故障时，
    自动平滑降级为进程内内存限流，确保高可用。
    """

    def __init__(self, limit: int, window_seconds: float, prefix: str = "xushi:ratelimit"):
        self.limit = max(1, limit)
        self.window = max(1.0, window_seconds)
        self.prefix = prefix
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _hit_memory(self, key: str, now: float) -> tuple[bool, int]:
        with self._lock:
            for stale in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > self.window]:
                del self._hits[stale]
            hits = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window]
            if len(hits) >= self.limit:
                retry_after = int(self.window - (now - hits[0])) + 1
                self._hits[key] = hits
                return False, max(1, retry_after)
            hits.append(now)
            self._hits[key] = hits
            return True, 0

    def hit(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 建议等待秒数)。"""
        now = time.time()
        client = get_redis()
        if not client:
            return self._hit_memory(key, time.monotonic())

        redis_key = f"{self.prefix}:{key}"
        try:
            pipe = client.pipeline()
            # 1. 移除窗口时间以外的旧记录
            pipe.zremrangebyscore(redis_key, 0, now - self.window)
            # 2. 统计当前窗口内记录总数
            pipe.zcard(redis_key)
            # 3. 获取当前窗口内最早的一条时间戳
            pipe.zrange(redis_key, 0, 0, withscores=True)
            _, count, oldest_entries = pipe.execute()

            if count >= self.limit:
                oldest_score = oldest_entries[0][1] if oldest_entries else now - self.window
                retry_after = max(1, int(self.window - (now - oldest_score)) + 1)
                return False, retry_after

            # 未达到限额，写入当前时间戳并延期
            member = f"{now}:{uuid.uuid4().hex[:6]}"
            pipe = client.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, int(self.window) + 10)
            pipe.execute()
            return True, 0
        except RedisError as exc:
            logger.warning("Redis 限流检查异常，平滑降级为内存限流: %s", exc)
            return self._hit_memory(key, time.monotonic())


# 小程序微信登录：单 IP 60 秒内最多 10 次（对齐母版登录限流强度）
login_limiter = SlidingWindowLimiter(limit=10, window_seconds=60, prefix="xushi:ratelimit:login")

# 账号互通绑定码校验：单用户 60 秒内最多 10 次，防遍历六位码
link_limiter = SlidingWindowLimiter(limit=10, window_seconds=60, prefix="xushi:ratelimit:link")

# 微信 ClawBot：单用户 60 秒内最多 10 次提问（防止刷爆 LLM Token 与阻塞线程池）
clawbot_limiter = SlidingWindowLimiter(limit=10, window_seconds=60, prefix="xushi:ratelimit:clawbot")

# 企业微信智能机器人：单用户 60 秒内最多 10 次提问
wecom_limiter = SlidingWindowLimiter(limit=10, window_seconds=60, prefix="xushi:ratelimit:wecom")


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() if settings.trust_proxy_headers else ""
    return forwarded or (request.client.host if request.client else "unknown")


def enforce_auth_rate_limit(request: Request, action: str) -> None:
    """邮箱注册/登录限流：登录用完整限额，注册减半（至少 3 次）。"""
    window = float(settings.auth_rate_window_seconds)
    limit = settings.auth_rate_limit if action == "login" else max(3, settings.auth_rate_limit // 2)
    key = client_ip(request)
    limiter = SlidingWindowLimiter(limit=limit, window_seconds=window, prefix=f"xushi:ratelimit:{action}")
    allowed, retry_after = limiter.hit(key)
    if not allowed:
        raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
