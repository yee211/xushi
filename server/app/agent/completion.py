"""Server-owned completion contract; model prose never creates background work."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ARCHIVE_TOOLS = {
    "query_day_courses", "query_week_courses", "get_next_course", "find_course",
    "query_other_day_courses", "check_group_availability", "list_other_people", "add_other_schedule",
    "remove_other_schedule", "clear_other_schedules",
    "compare_other_week_courses",
}
AMBIGUOUS_ERRORS = {"AMBIGUOUS_SCHEDULE", "AMBIGUOUS_PERSON", "ADD_NEEDS_INPUT", "NO_OTHER_SCHEDULES",
                    "PERSON_NOT_FOUND", "CLEAR_NEEDS_CONFIRM"}
OTHER_SCHEDULES_PROMPT = (
    "\n- 用户问某位同学本周/下周哪些课和我不一样时，用 compare_other_week_courses，日期传目标自然周内一天；差异正文由服务端生成。"
    "\n- 查询已保存的同学（室友、搭子等）某天课程用 query_other_day_courses，查询已保存同学列表用 list_other_people；"
    "\n- 询问某个时段“谁有空”或“我和某人/室友什么时候都有空（共同空闲）”用 check_group_availability；"
    "\n- 用户要求添加/保存某位同学的课表时，调用 add_other_schedule（若返回 status=ambiguous 候选列表，使用 needs_input 原样转达候选，请用户回复序号、班级或完整学号确认；若已唯一定位并保存成功，使用 completed 告知已添加）。"
    "\n- 用户要求删除/移除某位同学课表时，调用 remove_other_schedule（按备注或姓名匹配；未保存或匹配多人时按返回提示与候选转达）；"
    "\n- 用户要求清空全部同学课表时，调用 clear_other_schedules：首次不带 confirm，把待确认名单与人数原样转达；"
    "仅当用户在收到名单后明确回复确认（如“确认”“确定清空”），才带 confirm=true 和 expected_count=返回的 count 再次调用执行，"
    "用户否定、犹豫或改口时不得执行。"
)
COMPLETION_PROMPT = (
    '\n最终回复请输出 JSON 对象，固定字段为 status（completed、pending、needs_input 或 failed）、answer（给用户的文字）、task_id（无任务时为 null）。'
    '调用工具时仍使用 tool_calls。查询未执行不能标为 completed；不能编造 task_id，也不能以稍等或稍后回复结束。'
    '课程列表的 closing 输出要求优先，由服务端生成课程正文。缺少会影响结果的日期、课程或课表选择时，使用 needs_input 并只问一个具体问题；'
    '有候选时列出候选，不猜测。用户简短回复可能是在回答上一条追问，应结合原请求继续查询；用户取消或提出新问题时停止旧追问。'
    '信息足够时直接调用工具，不要无意义地反复确认。' + OTHER_SCHEDULES_PROMPT
)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "pending", "needs_input", "failed"]
    answer: str = Field(min_length=1)
    task_id: str | None = None

    @model_validator(mode="after")
    def pending_requires_task(self):
        if self.status == "pending" and not self.task_id:
            raise ValueError("pending response requires a verified task")
        return self


# Promises of future work are not final answers. Advice to ask again is allowed.
WAITING = re.compile(
    r"稍等|稍候|我(?:来|先|再|这就|马上)?查(?:一下|下|查)|等我(?:一下|一会|查)|(?:我|这边).{0,12}(?:帮你|替你|给你|为你).{0,8}(?:查查|查询|看看|查一下)(?![到完好了])"
    r"|(?:查完|查到|查好|完成后|好了后|稍后|一会儿?).{0,12}(?:告诉你|回复你|发给你|通知你)"
    r"|(?:正在|马上|这就).{0,8}(?:查询|查课|查一下|帮你查)"
)


def promises_work(text: str) -> bool:
    match = WAITING.search(text)
    if not match:
        return False
    # A conversational introduction followed by a concrete result is already complete.
    tail = text[match.end():]
    if re.search(r"[，,。\n]|(?<!\d)[:：]", tail) and re.search(r"\d{1,2}:\d{2}|第[一二三四五六七八九十0-9]+[节周]|[在有是].{0,30}\d|(?:没有|无)课", tail):
        return bool(WAITING.search(tail))
    return True


def query_failed(facts: list[dict]) -> bool:
    """Evaluate the latest result of each requested operation, excluding catalog help."""
    latest = {}
    facts = [fact for fact in facts if not fact.get("_superseded")]
    core = [fact for fact in facts if fact.get("skill") != "list_course_catalog"]
    for fact in core or facts:
        arguments = fact.get("arguments") or "{}"
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            arguments = json.dumps(args, sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            arguments = str(arguments)
        latest[(fact.get("skill"), arguments)] = fact.get("result") or {}
    # ok=False 且 status 为 ambiguous/needs_input 的结果是设计内的追问（如清空确认握手），
    # 不是查询失败，不应把同轮稍后已成功执行的操作判成 failed。
    return any(result.get("error") and result.get("status") not in {"ambiguous", "needs_input"}
               for result in latest.values())


def finalize(result: dict) -> dict:
    """Keep existing business fields; derive status only from execution results."""
    result = dict(result)
    data = result.get("tool_result") or {}
    status, task_id = "completed", None
    reported_status = None
    # A backend-provided schedule conflict is a question, not a failed query.
    if isinstance(data, dict):
        for fact in reversed(data.get("skills") or []):
            if fact.get("_superseded"):
                continue
            item = fact.get("result") or {}
            if fact.get("skill") in {"add_other_schedule", "clear_other_schedules"} and item.get("ok") is False:
                result["answer"] = item.get("message") or "未能完成同学课表操作，请重试。"
                reported_status = "needs_input" if item.get("status") in {"ambiguous", "needs_input"} else "failed"
                break
            if item.get("error") in AMBIGUOUS_ERRORS and item.get("candidates"):
                result["error"] = {"code": item["error"], "message": item["message"],
                                   "candidates": item["candidates"]}
                result["answer"] = item["message"]
                break
            if item.get("status") == "ambiguous" and item.get("candidates"):
                reported_status = "needs_input"
                break
            if fact.get("skill") in ARCHIVE_TOOLS and not item.get("error"):
                break
    model_status = result.pop("_completion_status", None)
    reported_status = reported_status or model_status
    if reported_status in {"failed", "needs_input"}:
        status = reported_status
    if result.get("error"):
        status = "needs_input" if result["error"].get("code") in AMBIGUOUS_ERRORS else "failed"
    elif result.get("intent") == "SYNC_SCHEDULE" or (result.get("intent") == "SYNC_OTHER_SCHEDULE" and data):
        if not data.get("ok") or data.get("state") == "failed":
            status = "failed"
        elif data.get("state") in {"queued", "running"} and data.get("job_id"):
            task_id = str(data["job_id"])
            status = "pending"
        elif data.get("state") in {"queued", "running"}:
            status = "failed"
            result["answer"] = "暂时无法确认同步任务编号，请查询同步进度。"
    elif (status != "needs_input" and isinstance(data, dict)
          and query_failed(data.get("skills") or [])):
        status = "failed"
    elif isinstance(data, dict) and (data.get("course_match") or {}).get("status") == "ambiguous":
        status = "needs_input"
    result["answer"] = str(result.get("answer") or "").strip()
    if not result["answer"]:
        result["answer"] = "这次未能生成有效回复，请重新发送你要查询的日期或课程。"
        status, task_id = "failed", None
    if promises_work(result["answer"]):
        # Only deterministic sync replies backed by registered delivery may promise a followup.
        registered = (result.get("intent") == "SYNC_SCHEDULE" and task_id
                      and data.get("notification_registered"))
        if not registered:
            result["answer"] = "这次未能完成查询，请重新发送你要查询的日期或课程。"
            status, task_id = "failed", None
    contract = Completion(status=status, answer=result["answer"], task_id=task_id)
    result.update(contract.model_dump())
    return result
