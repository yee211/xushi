"""HS256 JWT 签发与校验（网页端 / Android 客户端使用）。"""
from datetime import UTC, datetime, timedelta

import jwt

from ..settings import settings

JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = settings.jwt_expire_minutes


def create_token(user_id: int, username: str) -> str:
    """签发包含用户标识与过期时间的 HS256 JWT。"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(UTC) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """校验 JWT 并返回载荷；失败抛出 jwt.InvalidTokenError。"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
