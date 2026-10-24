"""Feedback identifiers shown in the admin panel."""
import hashlib
import os

CATEGORY_LABELS = {"import": "课表导入", "schedule": "课程显示", "adjustment": "调课",
                   "agent": "课表助手", "other": "其他"}


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
