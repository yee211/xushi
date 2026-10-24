"""Explicit sync authorization and deterministic submission replies."""
import re

PREFIX = r"^(?:请|麻烦|帮我|给我|现在|立即|重新|再|先)*"
COMMAND = r"(?:同步|更新|刷新)(?:一下|下)?(?:我的|学校|最新)*课表(?:一下|下)?"


def requested(message: str) -> bool:
    text = re.sub(r"\s+", "", message).strip("。！!，,")
    if re.search(r"不要同步|别同步|别真的同步|不用同步|不需要同步|取消同步", text):
        return False
    # Authorize an imperative at the start, never a quoted/history/status mention.
    prefix = PREFIX
    command = COMMAND
    match = re.match(prefix + command, text)
    if match:
        tail = text[match.end():]
        first_clause = re.split(r"[，,。！!]", tail, maxsplit=1)[0]
        if re.search(r"[？?]$|(?:吗|么)$", first_clause):
            return False
        return not bool(re.match(r"了(?:没|吗)|好了|成功|失败|进度|状态|怎么|为什么|是不是|是否|能否|要不要|只是|的意思|是什么", tail))
    return bool(re.fullmatch(prefix + r"(?:同步|更新|刷新)(?:一下|下)?[。！!]?", text))


def status_requested(message: str, history: list | None = None) -> bool:
    text = re.sub(r"\s+", "", message)
    # A mixed course/weather question or adding someone's schedule still goes through the query agent.
    if re.search(r"有(?:什么|啥|几节|多少|几门)课|(?:课|课程).{0,8}(?:在哪|教室|几点)|教室|带伞|天气|有没有.*课", text) or re.match(
            PREFIX + r"(?:添加|加一下|保存(?!的)|绑定).{0,30}课表", text):
        return False
    if re.search(r"同步|旧课表|学校绑定|课表.{0,8}(?:更新|刷新|最新)|(?:需要|要不要).{0,4}(?:更新|刷新)课表|(?:更新|刷新).{0,6}(?:好了吗|好了没|完成|进度|状态)", text):
        return True
    if re.fullmatch(r"(?:现在)?(?:好了没|好了吗|成功了吗|完成了吗|进度呢)[？?。]*", text):
        recent = " ".join(str(getattr(item, "content", "")) for item in (history or [])[-2:])
        return bool(re.search(r"SYNC_SCHEDULE|SCHEDULE_STATUS|同步", recent))
    return False


def job_answer(job: dict) -> str:
    from ..services.academic_sync_notifications import completion_text

    state = job.get("state")
    if state == "queued":
        if job.get("phase") == "retrying":
            return "同步暂时遇到问题，后台正在自动重试，尚未完成。"
        return "课表同步任务已提交，正在后台排队。"
    if state == "running":
        return "学校课表已获取，正在保存，同步尚未完成。" if job.get("phase") == "writing" else "课表正在后台同步，尚未完成。"
    if state in {"succeeded", "failed"}:
        return completion_text(job)
    return "暂时无法确定同步任务状态，请稍后再查。"


def status_reply(status: dict, message: str = "") -> dict:
    job = status.get("sync_job")
    if "学校绑定" in message:
        answer = "已绑定学校身份。" if status.get("school_bound") else "还没有绑定学校身份，请先在小程序中绑定。"
    elif job:
        answer = job_answer(job)
    elif not status.get("school_bound"):
        answer = "还没有绑定学校身份，请先在小程序中绑定，再发送“同步课表”。"
    else:
        answer = "没有查到同步任务记录。"
        answer += "当前有已保存的课表。" if status.get("schedules") else "还没有已保存的课表，可以发送“同步课表”来更新。"
        if status.get("last_synced_at"):
            answer += f"最近学校同步时间：{status['last_synced_at']}。"
    if re.search(r"最新|需要更新|要不要更新", message):
        if status.get("last_synced_at") and "最近学校同步时间" not in answer:
            answer += f"最近学校同步时间：{status['last_synced_at']}。"
        answer += "是否有新的学校调整需要再次同步确认，可以发送“同步课表”。"
    return {"intent": "SCHEDULE_STATUS", "answer": answer, "tool_result": status,
            "resolved_context": {"intent": "SCHEDULE_STATUS",
                                 "job_id": str(job["id"]) if job and job.get("id") else None,
                                 "job_state": job.get("state") if job else None}}


def query_status(tools, message: str) -> dict:
    try:
        return status_reply(tools.get_schedule_status(), message)
    except Exception:
        return {"intent": "SCHEDULE_STATUS", "answer": "暂时无法查询同步状态，请稍后重试。",
                "error": {"code": "service_unavailable"}}


def reply(result: dict, message: str = "") -> dict:
    if not result.get("ok"):
        answer = result.get("message", "暂时无法提交同步，请稍后重试。")
    else:
        answer = job_answer(result)
        if result.get("job_id") and result.get("state") in {"queued", "running"} and result.get("notification_registered") and not result.get("followup_registered"):
            answer += "完成后我会再发一条成功或失败通知。"
        if result.get("job_id") and result.get("state") in {"queued", "running"} and result.get("notification_registered") and result.get("followup_registered"):
            answer += "同步成功后，我会接着查询并回复你刚才问的课表；同步失败会说明原因。"
        elif result.get("state") in {"queued", "running", "succeeded"} and re.search(r"查|看看|有什么课|哪.*课", message):
            answer += "同步完成后，请再询问课表，我会读取更新后的数据。"
    return {"intent": "SYNC_SCHEDULE", "answer": answer, "tool_result": result,
            "resolved_context": {"intent": "SYNC_SCHEDULE", "job_id": result.get("job_id")}}
