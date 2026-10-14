"""Validated tool facts and a fixed day-course list layout."""
import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CourseRow(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    name: str = Field(min_length=1)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    teacher: str = ""
    room: str = ""

    @model_validator(mode="after")
    def chronological(self):
        if self.end_time <= self.start_time:
            raise ValueError("course end must follow start")
        return self


class DayCourses(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: date
    courses: list[CourseRow]
    period: str = "all"


class CourseComment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    closing: str = Field(default="", max_length=80)

    @field_validator("closing")
    @classmethod
    def single_line(cls, value):
        if "\n" in value or "\r" in value:
            raise ValueError("closing must be one line")
        return value.strip()


def list_question(message: str) -> bool:
    return bool(re.search(r"(?:什么|啥|几节|多少|哪些|几门).*课|课表|课程列表", message)) and not bool(
        re.search(r"天气|雨|伞|有没有|有空|空闲|同步|更新|老师|教师|教室|在哪|哪里", message))


def day_fact(facts: list[dict], message: str) -> DayCourses | None:
    if not list_question(message):
        return None
    hits = [fact for fact in facts if fact.get("skill") == "query_day_courses"]
    if len(hits) != 1 or hits[0]["result"].get("error"):
        return None
    result = hits[0]["result"]
    import json
    args = hits[0].get("arguments") or "{}"
    args = json.loads(args) if isinstance(args, str) else args
    return DayCourses.model_validate(dict(result, period=args.get("period", "all")))


def render_day(day: DayCourses, today: date, closing: str = "") -> str:
    delta = (day.date - today).days
    label = {0: "今天", 1: "明天", 2: "后天"}.get(delta, "")
    weekday = "一二三四五六日"[day.date.weekday()]
    stamp = f"{day.date.month}月{day.date.day}日，周{weekday}"
    title = f"{label}（{stamp}）" if label else f"{day.date.year}年{stamp}"
    title += {"morning": "上午", "afternoon": "下午", "evening": "晚上"}.get(day.period, "")
    if not day.courses:
        return title + "没有课。"
    lines = []
    for course in sorted(day.courses, key=lambda item: item.start_time):
        details = "，".join(value for value in (course.name, course.teacher, course.room) if value)
        lines.append(f"• {course.start_time}–{course.end_time} {details}")
    answer = title + f"有{len(day.courses)}节课：\n" + "\n".join(lines)
    return answer + ("\n\n" + closing if closing else "")
