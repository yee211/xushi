"""Separate explicit peer refresh requests from the user's own timetable."""
import re

from .sync import PREFIX, requested, status_requested


def target(message):
    if requested(message):
        return None
    text = re.sub(r"\s+", "", message).strip("。！!，,")
    match = re.fullmatch(PREFIX + r"(?:同步|更新|刷新)(?:一下|下)?(.+?)课表(?:一下|下)?", text)
    if not match:
        return None
    person = match[1].removesuffix("的")
    if person in {"我", "自己", "我自己", "学校", "最新"}:
        return None
    if re.search(r"不要|不用|别|取消|[？?吗么]|和|以及|然后|但是|全部课表", person):
        return ("clarify", "")
    if person in {"全部", "所有"}:
        return ("clarify", "")
    if re.fullmatch(r"(?:全部|所有)(?:已保存的?|收藏的?)?(?:同学|他人|室友)?", person) or person in {"同学全部", "同学所有"}:
        return ("all", "")
    if person in {"同学", "他人"}:
        return ("clarify", "")
    return ("person", person)


def status_reply(data):
    if not data.get("ok"):
        answer = data["message"]
    elif not data.get("job"):
        answer = "没有查到同学课表同步任务记录。"
    else:
        job = data["job"]
        names = "、".join(str(i["name"]) for i in job["items"])
        answer = f"同学课表同步（{names}）：已处理{job['done']}/{job['total']}人，更新{job['updated']}人，失败{job['failed']}人，跳过{job['skipped']}人。"
        answer += "仍在后台排队或同步，尚未完成。" if job["state"] in {"queued", "running"} else "任务已结束。"
    job = data.get("job") or {}
    return {"intent": "OTHER_SCHEDULE_STATUS", "answer": answer, "tool_result": data,
            "_completion_status": "failed" if not data.get("ok") else None,
            "resolved_context": {"intent": "OTHER_SCHEDULE_STATUS", "job_id": job.get("id")}}


def handle(message, tools, history=None):
    if requested(message):
        return None
    scope = target(message)
    if scope is None:
        text = re.sub(r"\s+", "", message)
        recent = " ".join(str(getattr(item, "content", "")) for item in (history or [])[-2:])
        peer_context = bool(re.search(r'"intent":\s*"(?:SYNC_OTHER_SCHEDULE|OTHER_SCHEDULE_STATUS)"', recent))
        explicit_peer = bool(re.search(r"同学|他人|室友|舍友|搭子", text))
        status_target = None
        command = re.sub(r"(?:同步)?(?:好了没|好了吗|完成了吗|成功了吗|进度|状态)[？?。]*$", "", text)
        if command != text:
            status_target = target(command)
        named = re.fullmatch(r"(.+?)的?课表(?:同步|更新|刷新)(?:好了没|好了吗|完成了吗|成功了吗|进度|状态)[？?。]*", text)
        if named:
            status_target = target("同步" + named[1].removesuffix("的") + "的课表")
        if status_target and status_target[0] == "person":
            return status_reply(tools.get_other_schedule_status(person=status_target[1]))
        explicit_self = bool(re.search(r"我的|自己的|学校绑定", text))
        if status_requested(message, history) and (explicit_peer or (peer_context and not explicit_self)):
            match = re.search(r'"job_id":\s*"([^"\n]+)"', recent) if peer_context and not explicit_peer else None
            return status_reply(tools.get_other_schedule_status(match[1] if match else None))
        return None
    kind, person = scope
    if kind == "clarify":
        return {"intent": "SYNC_OTHER_SCHEDULE", "answer": "请说明同步对象：同步我的课表、同步张三的课表，或同步全部同学课表。", "_completion_status": "needs_input"}
    tools.other_sync_authorized = scope
    data = tools.sync_all_other_schedules() if kind == "all" else tools.sync_other_schedule(person)
    return {"intent": "SYNC_OTHER_SCHEDULE", "answer": data["message"], "tool_result": data,
            "_completion_status": "failed" if not data.get("ok") else None,
            "resolved_context": {"intent": "SYNC_OTHER_SCHEDULE", "job_id": data.get("job_id")}}
