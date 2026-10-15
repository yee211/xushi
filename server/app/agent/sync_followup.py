"""Durable sync continuations: a frozen query plan, followed by a read-only graph.

The notification row is the durable wait point. Replaying the graph only reads
courses; it never submits jobs, invokes the model, or sends channel messages.
"""
import re
from datetime import date, datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .course_reply import CourseList, DayCourses, render_courses


class FollowupPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    kind: Literal["day", "week"]
    target_date: date
    period: Literal["all", "morning", "afternoon", "evening"] = "all"
    requested_at: datetime
    question: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_reference(self):
        if self.requested_at.tzinfo is None:
            raise ValueError("followup reference requires a timezone")
        if self.kind == "week" and (self.target_date.weekday() != 0 or self.period != "all"):
            raise ValueError("weekly followup requires Monday and the full week")
        return self


def prepare(message: str, now: datetime) -> dict | None:
    from .orchestrator import parse_intent
    from .sync import COMMAND, PREFIX, requested

    if not requested(message) or now.tzinfo is None:
        return None
    text = re.sub(r"\s+", "", message)
    match = re.match(PREFIX + COMMAND, text)
    if not match:
        return None
    query = text[match.end():].strip("，,。！!")
    date_start = re.search(r"今天|今日|明天|明日|后天|明早|(?:下下|上|下|本|这)?(?:周|星期)|这一周", query)
    if not date_start or not re.fullmatch(
            r"(?:(?:完成|同步)(?:之)?后|然后|之后|后|再|并|顺便|帮我|给我|告诉我|看看|查一下|查下|查询|查|，|,)*",
            query[:date_start.start()]):
        return None
    query = query[date_start.start():]
    # A single unambiguous day/week list is supported. Do not silently drop
    # weather, negation, course filters, time ranges or additional requests.
    if re.search(r"不|别|天气|雨|伞|同步|更新|刷新|或者|还是|和|及|到|至|[，,。；;]", query):
        return None
    if sum(word in query for word in ("今天", "明天", "后天")) > 1:
        return None
    if len(re.findall(r"(?:周|星期)[一二三四五六日天]", query)) > 1:
        return None
    if not re.fullmatch(r"(?:今天|今日|明天|明日|后天|明早|(?:下下|上|下|本|这)?(?:周|星期)[一二三四五六日天]?|这一周)"
                        r"(?:早上|上午|下午|晚上|晚间)?(?:的)?(?:有(?:什么|啥|几节|多少|哪些|几门)?课|(?:什么|啥|哪些)课|课表|课程列表|课|安排)(?:吗|呢|呀)?[？?！!。]*", query):
        return None
    intent = parse_intent(query, now.date())
    if intent.name != "QUERY_DAY" and intent.name != "QUERY_WEEK":
        return None
    if intent.target_date is None or (intent.name == "QUERY_WEEK" and re.search(r"上午|早上|下午|晚上|晚间", query)):
        return None
    return FollowupPlan(kind="day" if intent.name == "QUERY_DAY" else "week",
                        target_date=intent.target_date, period=intent.period,
                        requested_at=now, question=query).model_dump(mode="json")


class QueryState(TypedDict, total=False):
    result: dict
    answer: str


def answer(plan: FollowupPlan, tools) -> str:
    """Resume from the durable plan; no credentials or tools in graph state."""
    from langgraph.graph import END, START, StateGraph
    from langsmith import tracing_context

    def query(state):
        if plan.kind == "day":
            result = tools.get_courses_by_date(plan.target_date, plan.period)
        else:
            result = tools.get_courses_by_week(plan.target_date)
        expected_schedule = tools.context.default_schedule_id
        days = [result] if plan.kind == "day" else result.get("days", [])
        if expected_schedule is not None and any(day.get("schedule_id") != expected_schedule for day in days):
            raise ValueError("followup schedule mismatch")
        if result.get("error"):
            raise ValueError("followup query failed")
        return {"result": result}

    def render(state):
        result = state["result"]
        if plan.kind == "day":
            day = DayCourses.model_validate(dict(result, period=plan.period))
            if day.date != plan.target_date:
                raise ValueError("followup date mismatch")
            bundle = CourseList(days=[day])
        else:
            bundle = CourseList.model_validate(result)
            if bundle.week_start != plan.target_date:
                raise ValueError("followup week mismatch")
        # Label relative to delivery time. Absolute target dates were frozen
        # when the user asked, so a midnight crossing cannot move the query.
        return {"answer": render_courses(bundle, tools.context.now.date())}

    builder = StateGraph(QueryState)
    builder.add_node("query", query)
    builder.add_node("render", render)
    builder.add_edge(START, "query")
    builder.add_edge("query", "render")
    builder.add_edge("render", END)
    with tracing_context(enabled=False):
        return builder.compile().invoke({}, {"recursion_limit": 5})["answer"]


def completed_reply(result: dict, plan: dict, tools) -> str:
    """A reused completed job needs an immediate answer, not a new subscription."""
    import logging
    from ..services.academic_sync_followup import delivery_text
    from ..services.academic_sync_notifications import completion_text

    try:
        with tools._connection() as db:
            job = db.execute(
                "SELECT * FROM academic_sync_jobs WHERE id=%s AND user_id=%s",
                (result["job_id"], tools.context.user_id),
            ).fetchone()
        if not job or job["state"] != "succeeded":
            return "无法确认本次同步结果，没有继续查询，请重新发送同步及查课请求。"
        # Reuse the same binding revision, schedule ownership and frozen-date
        # checks as background delivery. This function never sends a message.
        return delivery_text({"user_id": tools.context.user_id, "followup": plan,
                              "attempts": 3, "delivery_text": None}, dict(job))
    except Exception:
        logging.getLogger(__name__).exception("Completed sync followup query failed")
        return completion_text(result) + "后续课表查询暂时不可用，请重新询问课表。"
