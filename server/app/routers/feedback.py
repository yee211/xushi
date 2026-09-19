"""用户反馈路由：网页端与小程序端共用。

响应是两端字段的并集：小程序用 id/feedback_no/status，
网页端读 message/feedback_id/feedback_number。
"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..auth import get_current_user
from ..db import connect, row_dict
from ..rate_limit import SlidingWindowLimiter
from ..schemas import FeedbackIn
from ..services.feedback import feedback_number, send_feedback_notification

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
feedback_limiter = SlidingWindowLimiter(limit=5, window_seconds=600)


@router.post("")
def create_feedback(payload: FeedbackIn, tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    allowed, retry_after = feedback_limiter.hit(user["id"])
    if not allowed:
        raise HTTPException(429, "提交过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    description = payload.description.strip()
    if len(description) < 5:
        raise HTTPException(400, "请至少填写 5 个字的问题描述")
    contact = payload.contact.strip()
    schedule_id = payload.schedule_id
    with connect() as db:
        if schedule_id:
            sch = db.execute("SELECT 1 FROM schedules WHERE id=%s", (schedule_id,)).fetchone()
            if not sch:
                schedule_id = None
        row = db.execute("""INSERT INTO feedbacks(user_id,schedule_id,category,description,contact,client_info,status)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,'pending') RETURNING *""",
            (user["id"], schedule_id, payload.category, description, contact,
             json.dumps(payload.client_info or {}, ensure_ascii=False))).fetchone()
    item = row_dict(row)
    item["feedback_no"] = feedback_number(item["id"], item.get("created_at"))
    # 异步通知企业微信机器人，失败不影响提交
    tasks.add_task(send_feedback_notification, item)
    return {
        "ok": True,
        "id": item["id"],
        "feedback_id": item["id"],
        "feedback_no": item["feedback_no"],
        "feedback_number": item["feedback_no"],
        "status": item.get("status", "pending"),
        "message": "感谢你的反馈，我们会尽快处理！",
    }
