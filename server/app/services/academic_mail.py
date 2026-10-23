"""Fixed QQ SMTP alerts for administrators, independent of the user-facing agent."""
import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime

from Crypto.Cipher import AES

from .academic import ROOT, AcademicError, _key

DIRECTORY = ROOT / "data" / "academic"
CONFIG = DIRECTORY / "mail-config.enc"
OUTBOX = DIRECTORY / "mail-outbox.json"
_lock = threading.RLock()
_wake = threading.Event()
_stop = threading.Event()
_thread = None
MAX_ATTEMPTS = 3
QUERY_RECHECK_SECONDS = 300
MAINTENANCE_ALERT_SECONDS = 1800


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "-" + secrets.token_hex(8) + ".tmp")
    temporary.write_bytes(content)
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def config():
    if not CONFIG.exists():
        return {}
    try:
        raw = CONFIG.read_bytes()
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=raw[:12])
        return json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
    except Exception as error:
        raise AcademicError("mail_config_unavailable", "邮件配置无法解密，请重新保存授权码", 503) from error


def outbox():
    if not OUTBOX.exists():
        return {}
    # Fail closed on a damaged deduplication record instead of sending duplicates.
    return json.loads(OUTBOX.read_text(encoding="utf-8"))


def save_outbox(data):
    atomic_write(OUTBOX, json.dumps(data).encode())


def public_status():
    with _lock:
        try:
            saved = config()
            config_error = ""
        except AcademicError as error:
            saved, config_error = {}, error.message
        try:
            data = outbox()
        except (OSError, ValueError):
            data = {"status": "failed", "last_error": "通知记录读取失败，请检查服务器存储"}
        return {"enabled": saved.get("enabled", False), "sender": saved.get("sender", ""),
                "recipient": saved.get("recipient", ""), "configured": bool(saved.get("authorization_code")),
                "smtp_host": "smtp.qq.com", "smtp_port": 465, "config_error": config_error,
                **{k: data.get(k) for k in ("status", "active", "last_sent_at", "last_error", "attempts", "next_attempt_at", "query_state", "query_checked_at")}}


def save_config(enabled, sender, recipient, authorization_code=""):
    sender, recipient = sender.strip().lower(), recipient.strip().lower()
    if not re.fullmatch(r"[a-z0-9._+-]+@(qq|foxmail)\.com", sender):
        raise AcademicError("mail_sender_invalid", "请输入 QQ 或 Foxmail 发件邮箱", 422)
    if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", recipient):
        raise AcademicError("mail_recipient_invalid", "请输入有效的通知收件邮箱", 422)
    with _lock:
        old = config() if CONFIG.exists() and not authorization_code.strip() else {}
        code = authorization_code.strip() or (old.get("authorization_code", "") if old.get("sender") == sender else "")
        if enabled and not code:
            raise AcademicError("mail_code_required", "启用通知前请填写 QQ 邮箱 SMTP 授权码", 422)
        if code and not re.fullmatch(r"[a-zA-Z0-9]{8,128}", code):
            raise AcademicError("mail_code_invalid", "SMTP 授权码格式无效", 422)
        saved = {"enabled": bool(enabled), "sender": sender, "recipient": recipient, "authorization_code": code}
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=os.urandom(12))
        raw, tag = cipher.encrypt_and_digest(json.dumps(saved).encode())
        atomic_write(CONFIG, cipher.nonce + tag + raw)
        data = outbox()
        if data.get("active") and data.get("status") not in {"sent", "sending", "unknown"}:
            data.update(status="pending" if enabled else "disabled", attempts=0, next_attempt_at=0, last_error="")
            save_outbox(data)
    _wake.set()
    return public_status()


def connection_event(state):
    with _lock:
        data = outbox()
        if state in {"connected", "stopped"}:
            if data.get("active"):
                data.update(active=False)
                if data.get("status") in {"pending", "disabled"}:
                    data.update(status="cancelled", next_attempt_at=None)
                save_outbox(data)
        elif (state in {"needs_login", "maintenance_error"} and not data.get("active")) or (
                state == "query_unavailable" and data.get("active") and data.get("severity") != "query_unavailable"):
            data.update(active=True, incident=secrets.token_hex(16), status="pending", attempts=0,
                        severity=state, query_checks=0, detected_at=datetime.now(UTC).isoformat(), next_attempt_at=0, last_error="")
            save_outbox(data)
            logging.getLogger(__name__).info("School notification incident: %s", state)
    _wake.set()


def verify_query_connection():
    from .academic import CcsutClient
    try:
        with CcsutClient() as client:
            client.grades()
        return "available"
    except AcademicError as error:
        return "unavailable" if error.code == "connection_expired" else "unknown"
    except Exception:
        return "unknown"


def process_one():
    with _lock:
        data, saved = outbox(), config()
        if (not data.get("active") or data.get("status") != "pending" or not saved.get("enabled")
                or (data.get("next_attempt_at") or 0) > time.time()):
            return
        incident = data["incident"]
        # A process crash after SMTP submission must not silently send it again.
        data.update(status="sending", attempts=data.get("attempts", 0) + 1, next_attempt_at=None)
        save_outbox(data)
    query_state = verify_query_connection()
    with _lock:
        current = outbox()
        if current.get("incident") != incident or not current.get("active"):
            return
        current.update(query_state=query_state, query_checked_at=datetime.now(UTC).isoformat())
        if query_state == "unavailable":
            current["severity"] = "query_unavailable"
        # A transient probe failure is not evidence that login expired. Keep
        # monitoring without consuming the SMTP retry budget.
        age = (datetime.now(UTC) - datetime.fromisoformat(current["detected_at"])).total_seconds()
        if query_state in {"unknown", "available"} and age < MAINTENANCE_ALERT_SECONDS:
            current.update(status="pending", attempts=current["attempts"] - 1,
                           query_checks=current.get("query_checks", 0) + 1,
                           next_attempt_at=time.time() + QUERY_RECHECK_SECONDS)
            save_outbox(current)
            return
        save_outbox(current)
    message = EmailMessage()
    message["From"] = saved["sender"]
    message["To"] = saved["recipient"]
    message["Subject"] = {"unavailable": "序时：学校查询连接不可用，请重新登录",
                          "available": "序时：学校自动维护持续异常，当前查询正常",
                          "unknown": "序时：学校维护持续异常，无法确认查询状态"}[query_state]
    message["Date"] = format_datetime(datetime.now(UTC))
    message["Message-ID"] = f"<xushi-school-{incident}@{saved['sender'].split('@')[1]}>"
    descriptions = {
        "available": "学校自动维护持续异常超过30分钟，但当前保存的学校查询会话仍可使用，课表仍可同步。请检查维护状态；仅凭本提醒无需重新登录。",
        "unavailable": "学校查询连接已不可用，可能是登录过期或查询权限变化，需要管理员重新完成登录。",
        "unknown": "自动维护需要人工处理；本次未能确认查询连接是否可用，不能据此判断登录已过期。",
    }
    message.set_content(descriptions[query_state] + "\n"
                        + ("请在管理页面重新完成学校登录。\n" if query_state == "unavailable" else
                         "请查看管理页面维护状态；自动重试期间无需重复提交验证码。\n")
                        + f"发现时间（UTC）：{data['detected_at']}\n"
                        "处理入口：https://xushi.tanzeng.xyz/admin#page=academic\n"
                        "停止维护会保留现有查询会话，但后续失效时需重新登录。")
    submitted = False
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15, context=ssl.create_default_context()) as smtp:
            smtp.login(saved["sender"], saved["authorization_code"])
            submitted = True
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
            # Persist success before QUIT, whose failure must not cause a resend.
            with _lock:
                current = outbox()
                if current.get("incident") == incident:
                    current.update(status="sent", last_sent_at=datetime.now(UTC).isoformat(), last_error="")
                    save_outbox(current)
            return
    except Exception as error:
        with _lock:
            current = outbox()
            if current.get("incident") != incident or current.get("status") == "sent":
                return
            permanent = isinstance(error, smtplib.SMTPAuthenticationError | smtplib.SMTPRecipientsRefused)
            rejected = isinstance(error, smtplib.SMTPResponseException)
            uncertain = submitted and not rejected and not permanent
            retry = (not permanent and not uncertain and current["attempts"] < MAX_ATTEMPTS
                     and (not rejected or 400 <= error.smtp_code < 500))
            current.update(status="unknown" if uncertain else "pending" if retry and current.get("active") else "failed",
                           last_error=("发送结果未确认，为避免重复提醒已停止重发" if uncertain else
                                       "邮箱认证失败，请检查 SMTP 授权码" if isinstance(error, smtplib.SMTPAuthenticationError) else
                                       "邮件发送失败：" + type(error).__name__),
                           next_attempt_at=time.time() + 60 * current["attempts"] if retry else None)
            save_outbox(current)


def worker():
    while not _stop.is_set():
        _wake.clear()
        try:
            process_one()
        except Exception:
            logging.getLogger(__name__).exception("Academic mail worker failed")
        _wake.wait(15)


def start():
    global _thread, _stop
    with _lock:
        if _thread and _thread.is_alive():
            return
        try:
            data = outbox()
        except (OSError, ValueError):
            data = {}
        if data.get("status") == "sending":
            data.update(status="unknown", last_error="服务重启前的发送结果未确认，已停止重发")
            save_outbox(data)
        _stop = threading.Event()
        _thread = threading.Thread(target=worker, daemon=True, name="academic-mail")
        _thread.start()


def stop():
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=45)
