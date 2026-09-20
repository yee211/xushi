"""Tests verifying in-place edits on original schedules without creating adjusted copies."""

from app.routers import adjustments, courses, schedules
from app.schemas import AdjustmentApplyItem, AdjustmentApplyRequest, CourseAdjustmentIn, CourseIn


class Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def test_update_course_on_original_schedule(monkeypatch):
    """验证直接在 original 课表上更新课程不会被拦截为只读。"""
    class MockDb:
        def __init__(self):
            self.updated = False
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "original"}])
            if "SELECT c.*,s.variant_type FROM courses c JOIN schedules" in sql:
                return Result([{
                    "id": 10, "schedule_id": 1, "name": "高数", "teacher": "李老师",
                    "room": "101", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2], "color": "#5B8DEF", "variant_type": "original"
                }])
            if "UPDATE courses SET" in sql:
                self.updated = True
                return Result([{
                    "id": 10, "schedule_id": 1, "name": "高等数学", "teacher": "李老师",
                    "room": "202", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2], "color": "#5B8DEF"
                }])
            if "INSERT INTO course_change_logs" in sql:
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    db = MockDb()
    monkeypatch.setattr(courses, "connect", lambda: db)
    payload = CourseIn(
        schedule_id=1, name="高等数学", teacher="李老师", room="202",
        weekday=1, start_section=1, end_section=2, weeks=[1, 2], color="#5B8DEF"
    )
    res = courses.update_course(10, payload, user={"id": 100})
    assert res["name"] == "高等数学"
    assert res["room"] == "202"
    assert db.updated is True


def test_delete_course_on_original_schedule(monkeypatch):
    """验证直接在 original 课表上删除课程成功。"""
    class MockDb:
        def __init__(self):
            self.deleted = False
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            if "DELETE FROM courses WHERE id=%s" in sql:
                self.deleted = True
                return Result([{"id": 10}])
            raise AssertionError(f"Unexpected SQL: {sql}")

    db = MockDb()
    monkeypatch.setattr(courses, "connect", lambda: db)
    courses.delete_course(10, user={"id": 100})
    assert db.deleted is True


def test_upsert_adjustment_on_original_schedule(monkeypatch):
    """验证在 original 课表上做单周调课直接成功，不需要创建调课版。"""
    class MockDb:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            if "SELECT c.*,s.variant_type FROM courses c JOIN schedules" in sql:
                return Result([{
                    "id": 10, "schedule_id": 1, "name": "高数", "room": "101",
                    "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [3], "variant_type": "original"
                }])
            if "SELECT * FROM course_adjustments WHERE course_id=%s AND week=%s" in sql:
                return Result([])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 1}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                return Result([])
            if "INSERT INTO course_adjustments" in sql:
                return Result([{
                    "id": 99, "course_id": 10, "week": 3, "weekday": 2,
                    "start_section": 3, "end_section": 4, "room": "303"
                }])
            if "INSERT INTO course_change_logs" in sql:
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(courses, "connect", lambda: MockDb())
    payload = CourseAdjustmentIn(week=3, weekday=2, start_section=3, end_section=4, room="303")
    res = courses.upsert_adjustment(10, 3, payload, idempotency_key=None, user={"id": 100})
    assert res["id"] == 99
    assert res["room"] == "303"


def test_apply_notice_on_original_schedule(monkeypatch):
    """验证批量应用调课通知可以直接应用在 original 课表上。"""
    class MockDb:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            if "SELECT id FROM schedules WHERE id=%s AND user_id=%s" in sql:
                return Result([{"id": 1}])
            if "SELECT * FROM courses WHERE id=%s AND schedule_id=%s" in sql:
                return Result([{
                    "id": 10, "schedule_id": 1, "name": "高数", "weekday": 1,
                    "start_section": 1, "end_section": 2, "weeks": [3], "room": "101"
                }])
            if "SELECT * FROM course_adjustments WHERE course_id=%s AND week=%s" in sql:
                return Result([])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 1}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                return Result([])
            if "INSERT INTO course_adjustments" in sql:
                return Result()
            if "INSERT INTO course_change_logs" in sql:
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(adjustments, "connect", lambda: MockDb())
    payload = AdjustmentApplyRequest(
        schedule_id=1,
        items=[AdjustmentApplyItem(
            course_id=10, week=3, weekday=2, start_section=3, end_section=4, room="303"
        )]
    )
    res = adjustments.apply_notice(payload, idempotency_key=None, user={"id": 100})
    assert res["applied"] == 1


def test_ensure_adjusted_schedule_returns_self(monkeypatch):
    """验证 ensure_adjusted_schedule 返回当前课表自身且 created=False。"""
    class MockDb:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            if "SELECT id FROM schedules WHERE id=%s AND user_id=%s" in sql:
                return Result([{"id": 42}])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(schedules, "connect", lambda: MockDb())
    res = schedules.ensure_adjusted_schedule(42, user={"id": 100})
    assert res["schedule_id"] == 42
    assert res["created"] is False
    assert res["course_map"] == {}
