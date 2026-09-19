"""Feedback identifiers and best-effort enterprise WeChat notifications."""
import hashlib
import json
import logging
import os

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
    salt = os.getenv("FEEDBACK_ANON_SALT", "wx-class-schedule-feedback")
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:8]


def send_feedback_notification(feedback: dict) -> bool:
    """Notify the owner's group robot; never raise into the request lifecycle."""
    webhook = os.getenv("WECOM_FEEDBACK_WEBHOOK_URL", "").strip()
    if not webhook:
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
    try:
        response = httpx.post(webhook, json={"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}}, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errcode") not in (None, 0):
            raise RuntimeError(payload.get("errmsg") or "企业微信机器人返回错误")
        return True
    except Exception as error:  # noqa: BLE001 - notification failure must not lose feedback
        logger.warning(json.dumps({"event": "feedback_notification_failed", "feedback_id": feedback["id"],
                                   "error": str(error)}, ensure_ascii=False))
        return False
