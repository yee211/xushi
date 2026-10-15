"""Resume an explicitly registered query after a successful school sync."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..agent.sync_followup import FollowupPlan, answer
from ..agent.tools import AgentContext, ScheduleTools
from ..db import connect
from .academic_sync_notifications import completion_text
from .schedule_query import ScheduleQueryError


def delivery_text(row: dict, job: dict) -> str:
    prefix = completion_text(job)
    if job["state"] != "succeeded":
        return prefix + "同步未成功，没有继续查询你刚才问的课表。"
    try:
        plan = FollowupPlan.model_validate(row["followup"])
    except (ValidationError, TypeError):
        return prefix + "后续查询记录无法读取，请重新询问课表。"
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if plan.requested_at.tzinfo is None or not timedelta(0) <= now - plan.requested_at <= timedelta(hours=24):
        return prefix + "原查询已超过有效期，请重新询问课表。"
    schedule_id = (job.get("result") or {}).get("schedule_id")
    if not isinstance(schedule_id, int) or isinstance(schedule_id, bool):
        return prefix + "暂时无法确认同步后的课表，请在小程序检查后重新询问。"
    # Recheck even when reusing a cached answer: unbinding/rebinding must never
    # deliver a previous school's courses. Pin queries to this sync's schedule.
    with connect() as db:
        binding = db.execute("""SELECT 1 FROM academic_bindings b JOIN schedules s ON s.user_id=b.user_id
            WHERE b.user_id=%s AND b.student->>'id'=%s AND b.revision=%s AND b.updated_at=%s
            AND s.id=%s""", (row["user_id"], job.get("student_id"), job.get("binding_revision"),
                              job.get("binding_updated_at"), schedule_id)).fetchone()
    if not binding:
        return prefix + "学校绑定或课表已发生变化，没有继续原查询，请重新询问。"
    if row.get("delivery_text"):
        return row["delivery_text"]
    if os.getenv("AGENT_ENGINE", "legacy").strip().lower() != "langgraph":
        return prefix + "自动续答暂未启用，请重新询问课表。"
    tools = ScheduleTools(connect, AgentContext(row["user_id"], now, "Asia/Shanghai", schedule_id))
    try:
        content = answer(plan, tools)
    except (ScheduleQueryError, ValueError, TypeError):
        return prefix + "后续课表查询失败或数据不完整，请重新询问课表。"
    except Exception:
        if row["attempts"] < 3:
            raise
        return prefix + "后续课表查询暂时不可用，请重新询问课表。"
    return prefix + "\n\n" + content
