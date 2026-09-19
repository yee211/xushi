"""鉴权层公共出口。

网页/Android 走 JWT，小程序走 sessions 表令牌；`get_current_user`
统一兼容两种通道（见 deps.py）。
"""
from .deps import get_current_user
from .jwt import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET, create_token, decode_token
from .passwords import hash_password, verify_password
from .sessions import token_hash
from .wechat import get_openid

__all__ = ["JWT_ALGORITHM", "JWT_EXPIRE_MINUTES", "JWT_SECRET", "create_token",
           "decode_token", "get_current_user", "get_openid", "hash_password",
           "token_hash", "verify_password"]
