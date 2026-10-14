"""Explicit sync authorization and deterministic submission replies."""
import re


def requested(message: str) -> bool:
    text = re.sub(r"\s+", "", message).strip("。！!，,")
    if re.search(r"不要同步|别同步|别真的同步|不用同步|不需要同步|取消同步", text):
        return False
    # Authorize an imperative at the start, never a quoted/history/status mention.
    prefix = r"^(?:请|麻烦|帮我|给我|现在|立即|重新|再|先)*"
    command = r"(?:同步|更新|刷新)(?:一下|下)?(?:我的|学校|最新)*课表(?:一下|下)?"
    match = re.match(prefix + command, text)
    if match:
        tail = text[match.end():]
        first_clause = re.split(r"[，,。！!]", tail, maxsplit=1)[0]
        if re.search(r"[？?]$|(?:吗|么)$", first_clause):
            return False
        return not bool(re.match(r"了(?:没|吗)|好了|成功|失败|进度|状态|怎么|为什么|是不是|是否|能否|要不要|只是|的意思|是什么", tail))
    return bool(re.fullmatch(prefix + r"(?:同步|更新|刷新)(?:一下|下)?[。！!]?", text))



def reply(result: dict, message: str = "") -> dict:
    if not result.get("ok"):
        answer = result.get("message", "暂时无法提交同步，请稍后重试。")
    else:
        state = result["state"]
        answer = {
            "queued": "同步任务已提交，正在后台排队，不用在这里等待。",
            "running": "课表正在后台同步，请稍后查询同步进度。",
            "succeeded": "刚刚已有同步任务完成，已复用这次结果。",
            "failed": "最近的同步任务失败，请在小程序检查学校连接，稍后重试；当前仍使用已保存的课表。",
        }.get(state, "已查询到同步任务，请稍后查询进度。")
        if state == "failed":
            from ..services.academic_sync_notifications import completion_text
            answer = completion_text(result)
        if result.get("notification_registered"):
            answer += "完成后我会再发一条成功或失败通知。"
        if state in {"queued", "running"} and re.search(r"查|看看|有什么课|哪.*课", message):
            answer += "同步完成后，请再询问课表，我会读取更新后的数据。"
    return {"intent": "SYNC_SCHEDULE", "answer": answer, "tool_result": result,
            "resolved_context": {"intent": "SYNC_SCHEDULE", "job_id": result.get("job_id")}}
