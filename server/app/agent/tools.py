import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..db import db_ctx
from ..services.academic_others import (
    check_group_availability,
    clear_saved_others,
    list_saved_summary,
    query_other_courses_by_date,
    remove_saved_other,
    resolve_saved_person,
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
        self.other_sync_authorized = None
        self._other_sync_result = None
        self._sync_result = None
        self.sync_followup = None
        self.clear_student_ids = None

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

    def remove_other_schedule(self, person: str = "", student_id: str = "") -> dict:
        with self._connection() as db:
            return remove_saved_other(db, self.context.user_id, person, student_id)

    def compare_other_week_courses(self, person: str, anchor_date: date) -> dict:
        from ..services.academic_others import _load_saved_rows, _materialize_other_row, _person_meta

        if not person.strip():
            raise ValueError("请指定要比较的同学姓名或备注")
        monday = anchor_date - timedelta(days=anchor_date.weekday())
        def signature(course):
            return tuple(str(course.get(k) or "").strip() for k in
                         ("name", "start_time", "end_time", "teacher", "room"))

        days = []
        with self._connection() as db:
            row = resolve_saved_person(_load_saved_rows(db, self.context.user_id), person)
            for offset in range(7):
                target = monday + timedelta(days=offset)
                other = _materialize_other_row(row, target)
                mine = query_courses_by_date(db, self.context.user_id, target, "all",
                                             self.context.default_schedule_id)
                other_keys = {signature(c) for c in other["courses"]}
                my_keys = {signature(c) for c in mine["courses"]}
                days.append({"date": target.isoformat(),
                             "other": {**other, "courses": [c for c in other["courses"] if signature(c) not in my_keys]},
                             "me": {**mine, "courses": [c for c in mine["courses"] if signature(c) not in other_keys]}})
        return {"person": _person_meta(row), "start_date": monday.isoformat(),
                "end_date": (monday + timedelta(days=6)).isoformat(), "days": days}

    def clear_other_schedules(self, confirm=False, expected_count: int | None = None) -> dict:
        # 不在此处 bool()：字符串 "false" 会被误判为真，收敛逻辑在 service 入口。
        with self._connection() as db:
            # 授权只能来自渠道入口中已持久化的上一轮追问，模型参数不能授权删除。
            return clear_saved_others(db, self.context.user_id,
                                      confirm if self.clear_student_ids is not None else False,
                                      expected_count, expected_student_ids=self.clear_student_ids)

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

    def sync_other_schedule(self, person: str) -> dict:
        return self._sync_others(("person", person.strip()))

    def sync_all_other_schedules(self) -> dict:
        return self._sync_others(("all", ""))

    def _sync_others(self, scope) -> dict:
        from fastapi import HTTPException

        from ..services import academic, academic_other_jobs, academic_others
        from ..services.schedule_query import ScheduleQueryError

        if self.other_sync_authorized != scope:
            return {"ok": False, "error": "explicit_request_required",
                    "message": "请明确发送“同步某某的课表”或“同步全部同学课表”。"}
        if self._other_sync_result is not None:
            return self._other_sync_result
        try:
            student_ids = None
            if scope[0] == "person":
                with self._connection() as db:
                    row = resolve_saved_person(academic_others._load_saved_rows(db, self.context.user_id), scope[1])
                student_ids = [row["student_id"]]
            job = academic_other_jobs.enqueue(self.context.user_id, student_ids=student_ids)
            data = {"ok": True, "scope": "others", "job_id": job["id"], **job,
                    "message": (f"同学课表同步任务已提交，共{job['total']}人，正在后台同步，尚未完成。"
                                if job["state"] in {"queued", "running"} else
                                f"同学课表任务已结束，更新{job['updated']}人，失败{job['failed']}人，跳过{job['skipped']}人。")}
        except ScheduleQueryError as error:
            data = {"ok": False, "error": error.code,
                    "message": error.message + " 请重新发送“同步姓名或唯一备注的课表”。"}
        except academic.AcademicError as error:
            data = {"ok": False, "error": error.code, "message": error.message}
        except HTTPException as error:
            data = {"ok": False, "error": "sync_rejected", "message": str(error.detail)}
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Agent peer sync submission failed")
            data = {"ok": False, "error": "submission_unknown",
                    "message": "暂时无法确认同学课表同步是否提交，请在小程序查看同步进度。"}
        self._other_sync_result = data
        return data

    def get_other_schedule_status(self, job_id: str | None = None, person: str = "") -> dict:
        from fastapi import HTTPException

        from ..services import academic_other_jobs, academic_others
        from ..services.schedule_query import ScheduleQueryError

        try:
            student_id = None
            if person:
                with self._connection() as db:
                    row = resolve_saved_person(academic_others._load_saved_rows(db, self.context.user_id), person)
                student_id = row["student_id"]
            job = academic_other_jobs.read(self.context.user_id, job_id)
            if job and student_id and student_id not in {i["student_id"] for i in job["items"]}:
                return {"ok": False, "error": "person_not_in_job", "message": "最近的同学同步任务不包含这位同学，请在小程序查看历史记录，或明确发起此人的同步。"}
            return {"ok": True, "job": job}
        except ScheduleQueryError as error:
            return {"ok": False, "error": error.code, "message": error.message}
        except HTTPException as error:
            return {"ok": False, "error": "job_unavailable", "message": str(error.detail)}
        except Exception:
            return {"ok": False, "error": "service_unavailable", "message": "暂时无法查询同学课表同步进度，请稍后重试。"}
