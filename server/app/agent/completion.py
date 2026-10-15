"""Server-owned completion contract; model prose never creates background work."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


COMPLETION_PROMPT = '\n最终回复请输出 JSON 对象，固定字段为 status（completed、pending、needs_input 或 failed）、answer（给用户的文字）、task_id（无任务时为 null）。调用工具时仍使用 tool_calls。查询未执行不能标为 completed；不能编造 task_id，也不能以稍等或稍后回复结束。课程列表的 closing 输出要求优先，由服务端生成课程正文。'


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
    return bool(WAITING.search(text))


def query_failed(facts: list[dict]) -> bool:
    """Evaluate the latest result of each requested operation, excluding catalog help."""
    import json

    latest = {}
    core = [fact for fact in facts if fact.get("skill") != "list_course_catalog"]
    for fact in core or facts:
        arguments = fact.get("arguments") or "{}"
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            arguments = json.dumps(args, sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            arguments = str(arguments)
        latest[(fact.get("skill"), arguments)] = fact.get("result") or {}
    return any(result.get("error") for result in latest.values())


def finalize(result: dict) -> dict:
    """Keep existing business fields; derive status only from execution results."""
    result = dict(result)
    data = result.get("tool_result") or {}
    status, task_id = "completed", None
    reported_status = result.pop("_completion_status", None)
    if reported_status in {"failed", "needs_input"}:
        status = reported_status
    if result.get("error"):
        status = "needs_input" if result["error"].get("code") == "AMBIGUOUS_SCHEDULE" else "failed"
    elif result.get("intent") == "SYNC_SCHEDULE":
        if not data.get("ok") or data.get("state") == "failed":
            status = "failed"
        elif data.get("state") in {"queued", "running"} and data.get("job_id"):
            task_id = str(data["job_id"])
            status = "pending"
        elif data.get("state") in {"queued", "running"}:
            status = "failed"
            result["answer"] = "暂时无法确认同步任务编号，请查询同步进度。"
    elif isinstance(data, dict) and query_failed(data.get("skills") or []):
        status = "failed"
    elif isinstance(data, dict) and (data.get("course_match") or {}).get("status") == "ambiguous":
        status = "needs_input"
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
