"""Regression tests for durable, truthful adjustment history."""
import json

import pytest
from fastapi import HTTPException

from app.routers import adjustments
from app.routers import courses as main
from app.schemas import CourseAdjustmentIn, CourseIn


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class AdjustmentDb:
    def __init__(self, previous=None, duplicate=False, fail_log=False):
        self.previous = previous
        self.duplicate = duplicate
        self.fail_log = fail_log
        self.adjustment_writes = 0
        self.log_params = None
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.rolled_back = exc_type is not None
        return False

    def execute(self, sql, params=None):
        if "SELECT c.*,s.variant_type" in sql:
            return Result([{"id": 7, "schedule_id": 2, "name": "高数", "room": "A101",
                "weekday": 1, "start_section": 1, "end_section": 2, "weeks": [3],
                "variant_type": "adjusted"}])
        if "SELECT 1 FROM course_change_logs" in sql:
            return Result([{"?column?": 1}] if self.duplicate else [])
        if "SELECT * FROM course_adjustments WHERE" in sql:
            return Result([self.previous] if self.previous else [])
        if "SELECT schedule_id FROM courses" in sql:
            return Result([{"schedule_id": 2}])
        if "FROM courses c LEFT JOIN course_adjustments" in sql:
            return Result([])
        if "INSERT INTO course_adjustments" in sql:
            self.adjustment_writes += 1
            return Result([{"id": 9, "course_id": 7, "week": 3, "weekday": 3,
                "start_section": 5, "end_section": 6, "room": "B202"}])
        if "INSERT INTO course_change_logs" in sql:
            if self.fail_log:
                raise RuntimeError("simulated log failure")
            self.log_params = params
            return Result()
        raise AssertionError(sql)


def payload():
    return CourseAdjustmentIn(week=3, weekday=3, start_section=5, end_section=6, room="B202")


def invoke(monkeypatch, db, key="req-1"):
    monkeypatch.setattr(main, "connect", lambda: db)
    return main.upsert_adjustment(7, 3, payload(), source="manual",
                                  idempotency_key=key, user={"id": 1})


def test_repeated_request_is_idempotent(monkeypatch):
    db = AdjustmentDb(duplicate=True)
    result = invoke(monkeypatch, db)
    assert result["duplicate"] is True
    assert db.adjustment_writes == 0 and db.log_params is None


def test_continuous_adjustment_logs_current_state_as_old(monkeypatch):
    previous = {"id": 8, "course_id": 7, "week": 3, "weekday": 2,
                "start_section": 3, "end_section": 4, "room": "A102"}
    db = AdjustmentDb(previous=previous)
    invoke(monkeypatch, db)
    details = json.loads(db.log_params[-2])
    assert details[0]["old_weekday"] == 2
    assert details[0]["old_start_section"] == 3
    assert details[0]["old_room"] == "A102"


def test_unchanged_adjustment_creates_neither_write_nor_log(monkeypatch):
    previous = {"id": 8, "course_id": 7, "week": 3, "weekday": 3,
                "start_section": 5, "end_section": 6, "room": "B202"}
    db = AdjustmentDb(previous=previous)
    result = invoke(monkeypatch, db)
    assert result["unchanged"] is True
    assert db.adjustment_writes == 0 and db.log_params is None


def test_log_failure_rolls_back_adjustment_transaction(monkeypatch):
    db = AdjustmentDb(fail_log=True)
    with pytest.raises(RuntimeError, match="simulated log failure"):
        invoke(monkeypatch, db)
    assert db.adjustment_writes == 1
    assert db.rolled_back is True


def test_add_course_can_write_directly_to_original_schedule(monkeypatch):
    class AddCourseDb:
        def __init__(self):
            self.insert_params = None
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "original"}])
            if "INSERT INTO courses" in sql:
                self.insert_params = params
                return Result([{"id": 17, "schedule_id": params[0], "name": params[1]}])
            raise AssertionError(sql)

    db = AddCourseDb()
    monkeypatch.setattr(main, "connect", lambda: db)
    course = CourseIn(schedule_id=2, name="手动新增课", teacher="张三", room="A101",
        weekday=1, start_section=1, end_section=2, weeks=[1, 2], color="#5B8DEF")
    result = main.add_course(course, user={"id": 1})
    assert result == {"id": 17, "schedule_id": 2, "name": "手动新增课"}
    assert db.insert_params[0:3] == (2, "手动新增课", "张三")


def test_revoke_adjustment_record(monkeypatch):
    class RevokeDb:
        def __init__(self):
            self.deleted = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, sql, params=None):
            if "SELECT l.* FROM course_change_logs" in sql:
                return Result([{"id": 14, "schedule_id": 2, "details": [
                    {"course_id": 7, "week": 3},
                    {"course_id": 8, "week": 3}
                ]}])
            if "DELETE FROM course_adjustments" in sql:
                self.deleted.append(params)
                return Result([{"id": 1}])
            raise AssertionError(sql)

    db = RevokeDb()
    monkeypatch.setattr(adjustments, "connect", lambda: db)
    res = adjustments.revoke_adjustment_record(14, user={"id": 1})
    assert res == {"revoked": 2, "total": 2}
    assert len(db.deleted) == 2


def test_edit_from_original_moves_linked_adjustments_by_same_delta(monkeypatch):
    class CourseDb:
        def __init__(self):
            self.adjustment_update = None
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "adjusted"}])
            if "SELECT c.*,s.variant_type FROM courses c JOIN schedules" in sql:
                return Result([{"id": 7, "schedule_id": 2, "name": "高数", "teacher": "张三",
                    "room": "A101", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2, 3], "color": "#5B8DEF"}])
            if "SELECT * FROM course_adjustments" in sql:
                return Result([{"course_id": 7, "week": 3, "weekday": 3,
                    "start_section": 5, "end_section": 6, "room": "B202"}])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 2}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                return Result([])
            if "UPDATE courses SET" in sql:
                return Result([{"id": 7, "weekday": 2, "start_section": 3, "end_section": 4}])
            if "UPDATE course_adjustments" in sql:
                self.adjustment_update = params
                return Result()
            if "INSERT INTO course_change_logs" in sql:
                return Result()
            raise AssertionError(sql)

    db = CourseDb()
    monkeypatch.setattr(main, "connect", lambda: db)
    course = CourseIn(schedule_id=2, name="高数", teacher="张三", room="A101",
        weekday=2, start_section=3, end_section=4, weeks=[1, 2, 3], color="#5B8DEF")
    main.update_course(7, course, link_adjustments=True, user={"id": 1})
    assert db.adjustment_update == (1, 2, 2, 7)


def test_edit_from_original_raises_conflict_if_linked_adjustment_collides(monkeypatch):
    class ConflictDb:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "adjusted"}])
            if "SELECT c.*,s.variant_type FROM courses c JOIN schedules" in sql:
                return Result([{"id": 7, "schedule_id": 2, "name": "高数", "teacher": "张三",
                    "room": "A101", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2, 3], "color": "#5B8DEF"}])
            if "SELECT * FROM course_adjustments" in sql:
                return Result([{"course_id": 7, "week": 3, "weekday": 3,
                    "start_section": 5, "end_section": 6, "room": "B202"}])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 2}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                return Result([{
                    "id": 8, "schedule_id": 2, "name": "英语", "weekday": 4, "start_section": 7,
                    "end_section": 8, "weeks": [3], "adjusted_week": None, "adjusted_weekday": None,
                    "adjusted_start": None, "adjusted_end": None
                }])
            raise AssertionError(sql)

    monkeypatch.setattr(main, "connect", lambda: ConflictDb())
    course = CourseIn(schedule_id=2, name="高数", teacher="张三", room="A101",
        weekday=2, start_section=3, end_section=4, weeks=[1, 2, 3], color="#5B8DEF")
    with pytest.raises(HTTPException) as exc:
        main.update_course(7, course, link_adjustments=True, user={"id": 1})
    assert exc.value.status_code == 409
    assert "冲突" in exc.value.detail

