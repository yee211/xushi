"""Short-lived Redis state for QR login initiated by the mini program."""
import json
import os
import uuid

from redis import Redis
from redis.exceptions import RedisError

TTL_SECONDS = 600


def _redis() -> Redis:
    url = os.getenv("AGENT_REDIS_URL", os.getenv("REDIS_URL", "")).strip()
    if not url:
        raise RuntimeError("微信 ClawBot 扫码登录需要配置 Redis")
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=45)


def reserve_start(user_id: int) -> None:
    """Limit QR creation to one request per user every ten seconds."""
    try:
        allowed = _redis().set(f"wx-schedule:ilink-login-rate:{int(user_id)}", "1", ex=10, nx=True)
    except RedisError as error:
        raise RuntimeError("暂时无法创建扫码会话，请稍后重试") from error
    if not allowed:
        raise RuntimeError("二维码生成太频繁，请十秒后重试")


def create_session(user_id: int, qrcode: str, image_url: str) -> dict:
    session = {"id": uuid.uuid4().hex, "user_id": int(user_id), "qrcode": qrcode,
               "image_url": image_url, "redirect_host": ""}
    try:
        _redis().setex(f"wx-schedule:ilink-login:{session['id']}", TTL_SECONDS,
                       json.dumps(session, ensure_ascii=False))
    except RedisError as error:
        raise RuntimeError("暂时无法保存扫码会话，请稍后重试") from error
    return session


def load_session_by_id(session_id: str) -> dict:
    try:
        payload = _redis().get(f"wx-schedule:ilink-login:{session_id}")
        session = json.loads(payload) if payload else None
    except (RedisError, ValueError, TypeError) as error:
        raise RuntimeError("暂时无法读取扫码会话，请稍后重试") from error
    if not session:
        raise LookupError("扫码会话不存在或已过期")
    return session


def load_session(session_id: str, user_id: int) -> dict:
    session = load_session_by_id(session_id)
    if int(session.get("user_id") or 0) != int(user_id):
        raise LookupError("扫码会话不存在或已过期")
    return session


def update_session(session: dict) -> None:
    try:
        _redis().setex(f"wx-schedule:ilink-login:{session['id']}", TTL_SECONDS,
                       json.dumps(session, ensure_ascii=False))
    except RedisError as error:
        raise RuntimeError("暂时无法更新扫码会话，请稍后重试") from error


def delete_session(session_id: str) -> None:
    try:
        _redis().delete(f"wx-schedule:ilink-login:{session_id}")
    except RedisError:
        pass
