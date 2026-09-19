"""小程序会话令牌：随机 Bearer token，仅存 SHA-256 摘要。"""
import hashlib


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
