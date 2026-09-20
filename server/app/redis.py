"""统一 Redis 客户端与连接池管理。

特性：
1. 单例 ConnectionPool 复用连接；
2. 读取统一 settings.redis_url（兼容 REDIS_URL 与 AGENT_REDIS_URL）；
3. 优雅降级（Graceful Degradation）：所有快捷辅助方法均捕获 RedisError，
   当 Redis 未配置或网络故障时记录 Warning 并安全降级，保证核心业务绝不中断；
4. 测试友好：提供 set_redis_client / reset_redis_client 便于单测打桩。
"""
import logging
import os
from typing import Any

from redis import ConnectionPool, Redis
from redis.exceptions import RedisError

from .settings import settings

logger = logging.getLogger("classschedule.redis")

_pool: ConnectionPool | None = None
_custom_client: Redis | None = None


def get_redis_url() -> str:
    return settings.redis_url or os.getenv("REDIS_URL", os.getenv("AGENT_REDIS_URL", "")).strip()


def get_redis() -> Redis | None:
    """获取 Redis 客户端单例。未配置或异常时返回 None。"""
    global _pool, _custom_client
    if _custom_client is not None:
        return _custom_client

    url = get_redis_url()
    if not url:
        return None

    try:
        if _pool is None:
            _pool = ConnectionPool.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=2.0,
                max_connections=20,
            )
        return Redis(connection_pool=_pool)
    except Exception as exc:
        logger.warning("Redis 连接池初始化失败，将降级处理: %s", exc)
        return None


def set_redis_client(client: Redis | None) -> None:
    """供单元测试或特殊场景注入自定义/Fake 客户端。"""
    global _custom_client
    _custom_client = client


def reset_redis_client() -> None:
    """重置注入的客户端与连接池。"""
    global _custom_client, _pool
    _custom_client = None
    if _pool is not None:
        try:
            _pool.disconnect()
        except Exception:
            pass
        _pool = None


def redis_get(key: str) -> str | None:
    """安全读取 key；发生异常或未配置时返回 None。"""
    client = get_redis()
    if not client:
        return None
    try:
        return client.get(key)
    except RedisError as error:
        logger.warning("Redis GET 失败 (key=%s)，降级为直查: %s", key, error)
        return None


def redis_set(key: str, value: Any, ex: int | None = None) -> bool:
    """安全设置 key；发生异常或未配置时返回 False。"""
    client = get_redis()
    if not client:
        return False
    try:
        val_str = value if isinstance(value, str) else str(value)
        client.set(key, val_str, ex=ex)
        return True
    except RedisError as error:
        logger.warning("Redis SET 失败 (key=%s): %s", key, error)
        return False


def redis_delete(*keys: str) -> bool:
    """安全删除 key；发生异常或未配置时返回 False。"""
    if not keys:
        return True
    client = get_redis()
    if not client:
        return False
    try:
        client.delete(*keys)
        return True
    except RedisError as error:
        logger.warning("Redis DELETE 失败 (keys=%s): %s", keys, error)
        return False
