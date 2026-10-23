import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from ..db import db_ctx
from ..services.academic_others import (
    check_group_availability,
    list_saved_summary,
    query_other_courses_by_date,
    search_and_save_other,
)
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
    notification_target: dict | None = None


class ScheduleTools:
    def __init__(self, db_or_factory, context: AgentContext):
        self._db_or_factory = db_or_factory
        self.context = context
        self.sync_authorized = False
        self._sync_result = None
        self.sync_followup = None

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

    def list_other_people(self) -> dict:
        with self._connection() as db:
            return list_saved_summary(db, self.context.user_id)

    def query_other_day_courses(self, person: str, target_date: date, period: str = "all") -> dict:
        with self._connection() as db:
            return query_other_courses_by_date(db, self.context.user_id, person, target_date, period)

    def check_group_availability(self, target_date: date, period: str = "all",
                                 people: list[str] | None = None, include_me: bool = True) -> dict:
        with self._connection() as db:
            return check_group_availability(db, self.context.user_id, target_date, period,
                                            people, include_me, self.context.default_schedule_id)

    def add_other_schedule(self, keyword: str = "", remark: str | None = None,
                           term: str = "", student_id: str = "") -> dict:
        from fastapi import HTTPException

        from ..services import academic
        try:
            return search_and_save_other(self._connection, self.context.user_id, keyword, remark, term, student_id)
        except academic.AcademicError as error:
            return {"ok": False, "error": error.code, "message": error.message}
        except HTTPException as error:
            return {"ok": False, "error": "save_failed", "message": str(error.detail)}


    def schedule_version(self) -> str:
        """Hash one consistent database snapshot, including edits and weekly overrides."""
        with self._connection() as db:
            row = db.execute("""
                SELECT jsonb_build_object(
                    'others', COALESCE((SELECT jsonb_agg(to_jsonb(o) ORDER BY o.student_id)
                        FROM academic_others o WHERE o.user_id=%s), '[]'::jsonb),
                    'binding', (SELECT jsonb_build_object('student_id', b.student->>'id',
                        'revision', b.revision, 'updated_at', b.updated_at)
                        FROM academic_bindings b WHERE b.user_id=%s),
                    'schedules', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)
                        FROM schedules s WHERE s.user_id=%s), '[]'::jsonb),
                    'courses', COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.id)
                        FROM courses c JOIN schedules s ON s.id=c.schedule_id WHERE s.user_id=%s), '[]'::jsonb),
                    'adjustments', COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id)
                        FROM course_adjustments a JOIN courses c ON c.id=a.course_id
                        JOIN schedules s ON s.id=c.schedule_id WHERE s.user_id=%s), '[]'::jsonb)
                ) AS snapshot
            """, (self.context.user_id,) * 5).fetchone()
        return hashlib.sha256(json.dumps(row["snapshot"], sort_keys=True, default=str,
                                         ensure_ascii=False).encode()).hexdigest()

    def get_schedule_status(self) -> dict:
        with self._connection() as db:
            schedules = db.execute("""SELECT id,name,term,start_date,end_date,academic_synced_at
                FROM schedules WHERE user_id=%s ORDER BY id DESC""", (self.context.user_id,)).fetchall()
            binding = db.execute("""SELECT last_synced_at,last_synced_term FROM academic_bindings
                WHERE user_id=%s""", (self.context.user_id,)).fetchone()
            job = db.execute("""SELECT id,term,state,phase,error,error_code,result,updated_at FROM academic_sync_jobs
                WHERE user_id=%s ORDER BY created_at DESC LIMIT 1""", (self.context.user_id,)).fetchone()
        return {"schedules": [dict(s) for s in schedules], "school_bound": binding is not None,
                "last_synced_at": binding["last_synced_at"] if binding else None,
                "last_synced_term": binding["last_synced_term"] if binding else None,
                "sync_job": dict(job) if job else None}


    def sync_schedule(self) -> dict:
        """Enqueue only; school network calls run in the existing background worker."""
        import logging
        import re

        from fastapi import HTTPException

        from ..services import academic_jobs

        if not self.sync_authorized:
            return {"ok": False, "error": "explicit_request_required",
                    "message": "请明确发送“同步课表”来发起同步。", "retryable": False}
        if self._sync_result is not None:
            return self._sync_result
        try:
            with self._connection() as db:
                binding = db.execute("SELECT student,last_synced_term FROM academic_bindings WHERE user_id=%s",
                                     (self.context.user_id,)).fetchone()
            if not binding:
                result = {"ok": False, "error": "school_not_bound",
                          "message": "请先在小程序绑定学校身份，再同步课表。", "retryable": False}
            else:
                term = binding.get("last_synced_term") or (binding.get("student") or {}).get("default_term")
                if not isinstance(term, str) or not re.fullmatch(r"\d{4}-\d{4}-[12]", term):
                    result = {"ok": False, "error": "term_required",
                              "message": "暂时无法确定同步学期，请先在小程序选择学期并同步。", "retryable": False}
                else:
                    options = {"cooldown_seconds": 30}
                    if self.context.notification_target:
                        options["notification_target"] = dict(self.context.notification_target)
                        if self.sync_followup:
                            options["notification_target"]["followup"] = self.sync_followup
                    job = academic_jobs.enqueue(self.context.user_id, term, True, **options)
                    result = {"ok": True, "job_id": str(job["id"]), "state": job["state"],
                              "term": job["term"], "phase": job.get("phase"), "result": job.get("result"), "error_code": job.get("error_code"), "notification_registered": bool(job.get("notification_registered")),
                              "followup_registered": bool(job.get("followup_registered"))}
        except HTTPException as error:
            result = {"ok": False, "error": "sync_rejected",
                      "message": str(error.detail), "retryable": False}
        except Exception:
            logging.getLogger(__name__).exception("Agent sync submission failed")
            result = {"ok": False, "error": "submission_unknown", "retryable": False,
                      "message": "暂时无法确认同步是否提交，请先查询同步进度，稍后再试。"}
        self._sync_result = result
        return result
