"""Feedback identifiers and best-effort enterprise WeChat notifications."""
import hashlib
import json
import logging
import os
import threading
import time

import httpx

logger = logging.getLogger("uvicorn.error")
CATEGORY_LABELS = {"import": "课表导入", "schedule": "课程显示", "adjustment": "调课",
                   "agent": "课表助手", "other": "其他"}


def safe_line(value) -> str:
    return " ".join(str(value or "").replace("<", "").replace(">", "").replace("`", "").split())


def feedback_number(feedback_id: int, created_at) -> str:
    if hasattr(created_at, "strftime"):
        date_text = created_at.strftime("%Y%m%d")
    elif created_at:
        date_text = str(created_at)[:10].replace("-", "")
    else:
        date_text = "00000000"
    return f"FB-{date_text}-{feedback_id:06d}"


def anonymous_user(user_id: int) -> str:
    salt = os.getenv("FEEDBACK_ANON_SALT", "").strip() or os.getenv("ADMIN_SESSION_SECRET", "").strip() or "wx-class-schedule-feedback"
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:8]


def _post_markdown(lines: list[str]) -> bool:
    """Post markdown to the group robot; never raise into the caller's lifecycle."""
    webhook = os.getenv("WECOM_FEEDBACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    try:
        response = httpx.post(webhook, json={"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}},
                              timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errcode") not in (None, 0):
            raise RuntimeError(payload.get("errmsg") or "企业微信机器人返回错误")
        return True
    except Exception as error:  # noqa: BLE001 - notification failure must not lose feedback
        logger.warning(json.dumps({"event": "wecom_notification_failed", "error": str(error)}, ensure_ascii=False))
        return False


def send_feedback_notification(feedback: dict) -> bool:
    """Notify the owner's group robot; never raise into the request lifecycle."""
    if not os.getenv("WECOM_FEEDBACK_WEBHOOK_URL", "").strip():
        return False
    number = feedback_number(feedback["id"], feedback.get("created_at"))
    client = feedback.get("client_info") or {}
    lines = [
        "## 序时 · 新问题反馈",
        f"> 编号：`{number}`",
        f"> 类型：{CATEGORY_LABELS.get(feedback['category'], '其他')}",
        f"> 描述：{safe_line(feedback['description'])}",
        f"> 用户：{anonymous_user(feedback['user_id'])}",
    ]
    device = " / ".join(filter(None, [client.get("platform"), client.get("system"), client.get("wechat_version")]))
    if device:
        lines.append(f"> 环境：{device}")
    if client.get("app_version"):
        lines.append(f"> 小程序版本：{client['app_version']}")
    if feedback.get("contact"):
        lines.append(f"> 联系邮箱：{safe_line(feedback['contact'])}")
    return _post_markdown(lines)


# 运维告警限频：同一 key 半小时内只发一次，避免后台任务重试风暴刷屏。
_alert_lock = threading.Lock()
_alert_last: dict[str, float] = {}
ALERT_INTERVAL_SECONDS = 1800.0


def notify_operator(title: str, details: list[str], *, key: str = "") -> bool:
    """面向管理员的运维告警（同一 key 限频）。发送放后台线程，绝不阻塞请求。"""
    key = safe_line(key or title)[:64]
    now = time.monotonic()
    with _alert_lock:
        last = _alert_last.get(key, 0.0)
        if now - last < ALERT_INTERVAL_SECONDS:
            return False
        _alert_last[key] = now
    lines = ["## 序时 · 运维告警", f"> {safe_line(title)}"]
    lines += [f"> {safe_line(item)}" for item in details if str(item).strip()]
    threading.Thread(target=_post_markdown, args=(lines,), daemon=True,
                     name="wecom-operator-alert").start()
    return True
