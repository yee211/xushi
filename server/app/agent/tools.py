import hashlib
import json
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


    def schedule_version(self) -> str:
        """Hash one consistent database snapshot, including edits and weekly overrides."""
        with self._connection() as db:
            row = db.execute("""
                SELECT jsonb_build_object(
                    'schedules', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)
                        FROM schedules s WHERE s.user_id=%s), '[]'::jsonb),
                    'courses', COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.id)
                        FROM courses c JOIN schedules s ON s.id=c.schedule_id WHERE s.user_id=%s), '[]'::jsonb),
                    'adjustments', COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id)
                        FROM course_adjustments a JOIN courses c ON c.id=a.course_id
                        JOIN schedules s ON s.id=c.schedule_id WHERE s.user_id=%s), '[]'::jsonb)
                ) AS snapshot
            """, (self.context.user_id,) * 3).fetchone()
        return hashlib.sha256(json.dumps(row["snapshot"], sort_keys=True, default=str,
                                         ensure_ascii=False).encode()).hexdigest()

    def get_schedule_status(self) -> dict:
        with self._connection() as db:
            schedules = db.execute("""SELECT id,name,term,start_date,end_date,academic_synced_at
                FROM schedules WHERE user_id=%s ORDER BY id DESC""", (self.context.user_id,)).fetchall()
            binding = db.execute("""SELECT last_synced_at,last_synced_term FROM academic_bindings
                WHERE user_id=%s""", (self.context.user_id,)).fetchone()
            job = db.execute("""SELECT state,phase,error,updated_at FROM academic_sync_jobs
                WHERE user_id=%s ORDER BY created_at DESC LIMIT 1""", (self.context.user_id,)).fetchone()
        return {"schedules": [dict(s) for s in schedules], "school_bound": binding is not None,
                "last_synced_at": binding["last_synced_at"] if binding else None,
                "last_synced_term": binding["last_synced_term"] if binding else None,
                "sync_job": dict(job) if job else None}
