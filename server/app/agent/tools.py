"""Read-only tools whose user identity is injected by trusted server context."""

from dataclasses import dataclass
from datetime import date, datetime

from ..services.schedule_query import (
    find_course,
    list_course_catalog,
    next_course,
    query_courses_by_date,
    query_courses_by_week,
)


@dataclass(frozen=True)
class AgentContext:
    user_id: int
    now: datetime
    timezone: str = "Asia/Shanghai"
    default_schedule_id: int | None = None

class ScheduleTools:
    def __init__(self, db, context: AgentContext):
        self.db, self.context = db, context

    def get_courses_by_date(self, target_date: date, period: str = "all") -> dict:
        return query_courses_by_date(self.db, self.context.user_id, target_date, period,
                                     self.context.default_schedule_id)

    def get_next_course(self, lookahead_days: int = 7) -> dict:
        return next_course(self.db, self.context.user_id, self.context.now, lookahead_days,
                           self.context.default_schedule_id)

    def get_courses_by_week(self, anchor_date: date, weekday: int | None = None) -> dict:
        return query_courses_by_week(self.db, self.context.user_id, anchor_date, weekday,
                                     self.context.default_schedule_id)

    def find_course(self, course_name: str, from_date: date, days: int = 30) -> dict:
        return find_course(self.db, self.context.user_id, course_name, from_date, days,
                           self.context.default_schedule_id)

    def list_course_catalog(self, target_date: date | None = None) -> list[dict]:
        return list_course_catalog(self.db, self.context.user_id,
                                   target_date or self.context.now.date(),
                                   self.context.default_schedule_id)
