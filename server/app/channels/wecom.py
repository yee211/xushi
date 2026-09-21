"""企业微信智能机器人渠道（URL 回调模式）：验签加解密、response_url 回复与课表问答调度。

协议（2025 版智能机器人，区别于经典自建应用回调，文档 path/101033、100719、101138）：
- 签名 = sha1(排序(token, timestamp, nonce, encrypt))；
- 密文 = Base64(AES-256-CBC(random(16) + len(4,大端) + 明文 + receiveid))，IV = AESKey[:16]；
  自建机器人场景 receiveid 为空字符串；
- 回调信封为 JSON {"encrypt": "..."}，解密后的报文也是 JSON（msgid/from.userid/response_url/...）；
- 回复不使用 access_token：POST 回调携带的 response_url（一次性，1 小时有效），
  body 为 markdown 或模板卡片；普通文本消息没有可用的被动回复形式。
"""
import hashlib
import json
import logging
import os
import secrets
import struct
import time
from base64 import b64decode, b64encode
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from ..agent.service import build_agent_reply
from ..db import connect
from ..rate_limit import wecom_limiter

WECOM_PROVIDER = "wecom"
CALLBACK_TIMEOUT = httpx.Timeout(10.0)
DEDUP_TTL_SECONDS = 300
MAX_REPLY_CHARS = 4000

logger = logging.getLogger("uvicorn.error")


class WeComCryptoError(RuntimeError):
    pass


def wecom_settings() -> dict | None:
    """读取渠道配置；完全未配置返回 None，配置不完整或密钥格式错误抛错。

    必填：WECOM_CALLBACK_TOKEN、WECOM_ENCODING_AES_KEY（回调配置中生成）。
    可选：WECOM_AIBOT_ID（校验报文归属）、WECOM_CORP_ID（receiveid 非空时校验）。
    """
    values = {name: os.getenv(name, "").strip() for name in (
        "WECOM_CALLBACK_TOKEN", "WECOM_ENCODING_AES_KEY", "WECOM_AIBOT_ID", "WECOM_CORP_ID")}
    if not any(values.values()):
        return None
    missing = [name for name in ("WECOM_CALLBACK_TOKEN", "WECOM_ENCODING_AES_KEY") if not values[name]]
    if missing:
        raise RuntimeError(f"企业微信机器人渠道配置不完整，缺少：{', '.join(missing)}")
    key = values["WECOM_ENCODING_AES_KEY"] + "="
    try:
        aes_key = b64decode(key)
    except ValueError as error:
        raise RuntimeError("WECOM_ENCODING_AES_KEY 不是合法的 Base64") from error
    if len(aes_key) != 32:
        raise RuntimeError("WECOM_ENCODING_AES_KEY 解码后必须为 32 字节")
    return {"token": values["WECOM_CALLBACK_TOKEN"], "aes_key": aes_key,
            "aibot_id": values["WECOM_AIBOT_ID"], "corp_id": values["WECOM_CORP_ID"]}


def message_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypt])).encode()).hexdigest()


def verify_signature(token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
    return secrets.compare_digest(message_signature(token, timestamp, nonce, encrypt), str(msg_signature or ""))


def encrypt_message(plain: str, aes_key: bytes, receive_id: str = "") -> str:
    raw = plain.encode()
    payload = get_random_bytes(16) + struct.pack("!I", len(raw)) + raw + receive_id.encode()
    pad = 32 - len(payload) % 32
    payload += bytes([pad]) * pad
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    return b64encode(cipher.encrypt(payload)).decode()


def decrypt_message(encrypt_b64: str, aes_key: bytes, corp_id: str = "") -> str:
    try:
        cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
        padded = cipher.decrypt(b64decode(encrypt_b64))
        buffer = padded[:-padded[-1]] if padded else b""
        if len(buffer) < 20:
            raise WeComCryptoError("解密后的内容过短")
        length = struct.unpack("!I", buffer[16:20])[0]
        plain, receive_id = buffer[20:20 + length], buffer[20 + length:]
    except (IndexError, struct.error) as error:
        raise WeComCryptoError("回调密文结构不合法") from error
    receive = receive_id.decode("utf-8", "replace")
    if receive and corp_id and receive != corp_id:
        raise WeComCryptoError("回调 receiveid 与 WECOM_CORP_ID 不匹配")
    return plain.decode("utf-8")


def parse_encrypt_envelope(body: bytes) -> str:
    """回调信封是 JSON：{"encrypt": "..."}。"""
    try:
        envelope = json.loads(body.decode("utf-8"))
        encrypt = envelope["encrypt"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
        raise WeComCryptoError("回调报文不是合法的加密信封") from error
    if not isinstance(encrypt, str) or not encrypt:
        raise WeComCryptoError("回调报文缺少 encrypt 字段")
    return encrypt


def parse_message(plain: str) -> dict:
    try:
        message = json.loads(plain)
    except ValueError as error:
        raise WeComCryptoError("解密后的报文不是合法 JSON") from error
    if not isinstance(message, dict):
        raise WeComCryptoError("解密后的报文不是 JSON 对象")
    return message


def verify_callback_url(settings: dict, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
    """企业微信后台「验证 URL 有效性」：验签后返回解密出的 echostr 明文（1 秒内原样响应）。"""
    if not verify_signature(settings["token"], timestamp, nonce, echostr, msg_signature):
        raise WeComCryptoError("URL 验证签名不通过")
    return decrypt_message(echostr, settings["aes_key"], settings.get("corp_id", ""))


def handle_callback(settings: dict, body: bytes, msg_signature: str, timestamp: str, nonce: str,
                    background_tasks) -> None:
    """验签解密并调度回复；立即返回空包，实际答复经 response_url 在后台推送。"""
    encrypt = parse_encrypt_envelope(body)
    if not verify_signature(settings["token"], timestamp, nonce, encrypt, msg_signature):
        raise WeComCryptoError("回调签名校验失败")
    message = parse_message(decrypt_message(encrypt, settings["aes_key"], settings.get("corp_id", "")))
    expected_bot = settings.get("aibot_id", "")
    if expected_bot and message.get("aibotid") not in ("", expected_bot):
        logger.warning(json.dumps({"event": "wecom_unknown_bot", "aibotid": message.get("aibotid")}))
        return
    sender = (message.get("from") or {}).get("userid", "")
    msg_type, chat_type = message.get("msgtype", ""), message.get("chattype", "single")
    response_url = message.get("response_url", "")
    logger.info(json.dumps({"event": "wecom_message", "msg_type": msg_type, "chat_type": chat_type}))
    key = message.get("msgid", "") or f"{sender}:{timestamp}:{msg_type}"
    if not _first_time_seen(key):
        return
    if chat_type != "single":
        return  # MVP 只处理单聊，群聊不响应
    content = (message.get("text") or {}).get("content", "") if msg_type == "text" else ""
    if msg_type != "text" and not response_url:
        return  # 无 response_url 的事件（如进入会话以外的通知）无法回复，忽略
    received_at = datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai")))
    background_tasks.add_task(process_wecom_message, content, sender, response_url, key, received_at)


_seen_messages: dict[str, float] = {}


def _first_time_seen(msg_key: str) -> bool:
    """企业微信可能重推同一消息，按 msgid（或事件键）做进程内幂等。"""
    now = time.time()
    for stale_key, seen_at in list(_seen_messages.items()):
        if now - seen_at > DEDUP_TTL_SECONDS:
            _seen_messages.pop(stale_key, None)
    if not msg_key or msg_key in _seen_messages:
        return False
    _seen_messages[msg_key] = now
    return True


def build_reply(db, content: str, sender_id: str, received_at: datetime | None = None) -> str:
    return build_agent_reply(db, content, WECOM_PROVIDER, sender_id, received_at,
                             os.getenv("APP_TIMEZONE", "Asia/Shanghai"))


def process_wecom_message(content: str, sender_id: str, response_url: str, msg_key: str = "",
                          received_at: datetime | None = None) -> None:
    """后台任务：生成回复并 POST 到 response_url；失败只记日志，不影响回调响应。"""
    try:
        allowed, retry_after = wecom_limiter.hit(sender_id)
        if not allowed:
            reply = f"你提问太频繁啦，请慢一点~ 请等待 {retry_after} 秒后再问我吧。"
            if response_url:
                reply_via_response_url(response_url, reply)
            logger.warning(json.dumps({"event": "wecom_rate_limited", "sender": sender_id}))
            return

        reply = build_reply(connect, content, sender_id, received_at)
        if reply and response_url:
            reply_via_response_url(response_url, reply)
            logger.info(json.dumps({"event": "wecom_reply_sent", "sender": sender_id}))
    except Exception:
        logger.exception(json.dumps({"event": "wecom_push_failed", "sender": sender_id, "msg_key": msg_key}))


def reply_via_response_url(response_url: str, content: str) -> None:
    """主动回复接口无需鉴权；response_url 一次性且 1 小时有效，markdown 上限 20480 字节。"""
    response = httpx.post(response_url, timeout=CALLBACK_TIMEOUT,
                          json={"msgtype": "markdown", "markdown": {"content": content[:MAX_REPLY_CHARS]}})
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"企业微信回复失败：{data.get('errcode')} {data.get('errmsg')}")
