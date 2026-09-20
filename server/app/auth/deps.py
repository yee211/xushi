"""统一鉴权依赖：同一套 Bearer 头兼容两种令牌通道。

- 网页/Android：/api/login、/api/register 签发的 HS256 JWT（无状态，形如 a.b.c）；
- 小程序：/api/auth/wechat 签发的随机 token（token_urlsafe，不含点），
  摘要存 sessions 表（可撤销、有过期）。

分发规则：令牌形如 JWT（恰含两个点）直接走 JWT 校验，不产生数据库查询；
其余令牌先查 sessions 表（主键命中），未命中再按 JWT 兜底解析——两类令牌
空间不重叠，互不干扰。
"""
import json
from datetime import UTC, datetime

import jwt
from fastapi import Header, HTTPException

from ..db import connect
from ..redis import redis_delete, redis_get, redis_set
from ..settings import settings
from .jwt import decode_token
from .sessions import token_hash

USER_COLUMNS = "u.id, u.openid, u.email, u.username"
SESSION_CACHE_PREFIX = "xushi:session:"


def invalidate_session_cache(token: str | None = None, token_digest: str | None = None) -> None:
    """撤销会话或账号合并时主动失效指定会话缓存。"""
    digest = token_digest or (token_hash(token) if token else None)
    if digest:
        redis_delete(f"{SESSION_CACHE_PREFIX}{digest}")


def _user_from_session(token: str) -> dict | None:
    digest = token_hash(token)
    cache_key = f"{SESSION_CACHE_PREFIX}{digest}"
    cached = redis_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except (ValueError, TypeError):
            pass

    with connect() as db:
        row = db.execute(f"""SELECT {USER_COLUMNS}, s.expires_at FROM sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.expires_at>CURRENT_TIMESTAMP""", (digest,)).fetchone()
    if not row:
        return None

    user_dict = {col: row[col] for col in ("id", "openid", "email", "username") if col in row}
    # 写入 Redis 缓存，TTL 与数据库 expires_at 实际剩余时间对齐（最长不超过 session_days）
    ttl_seconds = settings.session_days * 86400
    if row.get("expires_at"):
        exp = row["expires_at"]
        now = datetime.now(UTC) if exp.tzinfo else datetime.now()
        remain = int((exp - now).total_seconds())
        ttl_seconds = max(60, min(remain, ttl_seconds))
    redis_set(cache_key, json.dumps(user_dict), ex=ttl_seconds)
    return user_dict


def _user_from_jwt(token: str) -> dict:
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
        if user_id <= 0:
            raise ValueError("invalid user id")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(401, "无效的登录凭证")
    return {"id": user_id, "openid": None, "email": None, "username": payload.get("username", "")}


def _looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI 依赖：解析 Bearer 令牌并返回当前登录用户，失败时抛出 401。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    token = authorization[7:].strip()
    if _looks_like_jwt(token):
        return _user_from_jwt(token)
    user = _user_from_session(token)
    if user:
        return user
    # 非会话令牌：尝试按 JWT 解析（兼容旧客户端），失败统一按无效凭证处理
    return _user_from_jwt(token)
