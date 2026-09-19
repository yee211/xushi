"""PBKDF2-SHA256 密码哈希（网页端邮箱账号体系）。"""
import hashlib
import hmac
import secrets

_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 加盐哈希，存储格式：pbkdf2_sha256$迭代次数$salt$hash。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码与存储哈希是否匹配，使用 compare_digest 防止时序攻击。"""
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False
