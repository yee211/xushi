from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from ..db import db_ctx
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
    def __init__(self, db_or_factory, context: AgentContext):
        self._db_or_factory = db_or_factory
        self.context = context

    @property
    def db(self):
        """仅用于兼容裸连接读取；传入工厂时必须通过内部借还逻辑。"""
        if callable(self._db_or_factory):
            raise RuntimeError("ScheduleTools 使用连接工厂时请通过 _connection() 借还连接")
        return self._db_or_factory

    @contextmanager
    def _connection(self):
        """按需借出数据库连接，执行完毕立即归还池中，避免长任务霸占连接。"""
        with db_ctx(self._db_or_factory) as db:
            yield db

    def get_courses_by_date(self, target_date: date, period: str = "all") -> dict:
        with self._connection() as db:
            return query_courses_by_date(db, self.context.user_id, target_date, period,
                                         self.context.default_schedule_id)

    def get_next_course(self, lookahead_days: int = 7) -> dict:
        with self._connection() as db:
            return next_course(db, self.context.user_id, self.context.now, lookahead_days,
                               self.context.default_schedule_id)

    def get_courses_by_week(self, anchor_date: date, weekday: int | None = None) -> dict:
        with self._connection() as db:
            return query_courses_by_week(db, self.context.user_id, anchor_date, weekday,
                                         self.context.default_schedule_id)

    def find_course(self, course_name: str, from_date: date, days: int = 30) -> dict:
        with self._connection() as db:
            return find_course(db, self.context.user_id, course_name, from_date, days,
                               self.context.default_schedule_id)

    def list_course_catalog(self, target_date: date | None = None) -> list[dict]:
        with self._connection() as db:
            return list_course_catalog(db, self.context.user_id,
                                       target_date or self.context.now.date(),
                                       self.context.default_schedule_id)

