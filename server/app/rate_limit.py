"""进程内滑动窗口限流。

SlidingWindowLimiter 是通用实现（微信登录/反馈/管理后台登录使用）；
enforce_auth_rate_limit 在其上封装邮箱注册登录的限制规则，限额来自
settings（网页母版的 AUTH_RATE_LIMIT / AUTH_RATE_WINDOW_SECONDS），
并支持 TRUST_PROXY_HEADERS 场景下从 X-Forwarded-For 取真实来源。
多实例部署时需替换为 Redis 共享实现。
"""
import threading
import time

from fastapi import HTTPException, Request

from .settings import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = max(1, limit)
        self.window = max(1.0, window_seconds)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 建议等待秒数)，并顺手清理过期键。"""
        now = time.monotonic()
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


# 小程序微信登录：单 IP 60 秒内最多 10 次（对齐母版登录限流强度）
login_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)

# 账号互通绑定码校验：单用户 60 秒内最多 10 次，防遍历六位码
link_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)

_auth_attempts: dict[str, list[float]] = {}
_auth_lock = threading.Lock()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() if settings.trust_proxy_headers else ""
    return forwarded or (request.client.host if request.client else "unknown")


def enforce_auth_rate_limit(request: Request, action: str) -> None:
    """邮箱注册/登录限流：登录用完整限额，注册减半（至少 3 次）。"""
    window = settings.auth_rate_window_seconds
    limit = settings.auth_rate_limit if action == "login" else max(3, settings.auth_rate_limit // 2)
    key = f"{action}:{client_ip(request)}"
    now = time.monotonic()
    with _auth_lock:
        hits = [stamp for stamp in _auth_attempts.get(key, []) if now - stamp < window]
        if len(hits) >= limit:
            retry_after = max(1, int(window - (now - hits[0])))
            _auth_attempts[key] = hits
            raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
        hits.append(now)
        _auth_attempts[key] = hits
        # 顺手清理一小批已完全过期的来源，避免公网长期运行时字典只增不减
        if len(_auth_attempts) > 1024:
            for stale_key in [k for k, v in list(_auth_attempts.items())[:128] if not v or now - v[-1] >= window]:
                if stale_key != key:
                    _auth_attempts.pop(stale_key, None)
