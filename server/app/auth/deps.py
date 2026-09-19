"""统一鉴权依赖：同一套 Bearer 头兼容两种令牌通道。

- 网页/Android：/api/login、/api/register 签发的 HS256 JWT（无状态，形如 a.b.c）；
- 小程序：/api/auth/wechat 签发的随机 token（token_urlsafe，不含点），
  摘要存 sessions 表（可撤销、有过期）。

分发规则：令牌形如 JWT（恰含两个点）直接走 JWT 校验，不产生数据库查询；
其余令牌先查 sessions 表（主键命中），未命中再按 JWT 兜底解析——两类令牌
空间不重叠，互不干扰。
"""
import jwt
from fastapi import Header, HTTPException

from ..db import connect
from .jwt import decode_token
from .sessions import token_hash

USER_COLUMNS = "u.id, u.openid, u.email, u.username"


def _user_from_session(token: str) -> dict | None:
    digest = token_hash(token)
    with connect() as db:
        row = db.execute(f"""SELECT {USER_COLUMNS} FROM sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.expires_at>CURRENT_TIMESTAMP""", (digest,)).fetchone()
    return dict(row) if row else None


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
