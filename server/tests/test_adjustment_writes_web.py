"""Tests for adjustment writes: linked adjustment shifting, revocation, and building prefix completion."""
import pytest
from fastapi import HTTPException

from app.routers.adjustments import match_extracted, revoke_adjustment_record
from app.routers.courses import CourseIn, update_course


class Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def test_edit_course_moves_linked_adjustments_by_delta(monkeypatch):
    class MockDb:
        def __init__(self):
            self.adjustment_update = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "adjusted"}])
            if "SELECT c.*,s.variant_type FROM courses c" in sql:
                return Result([{
                    "id": 7, "schedule_id": 2, "name": "高数", "teacher": "张三",
                    "room": "A101", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2, 3], "color": "#5B8DEF"
                }])
            if "SELECT * FROM course_adjustments" in sql:
                return Result([{
                    "id": 10, "course_id": 7, "week": 3, "weekday": 3,
                    "start_section": 5, "end_section": 6, "room": "B202"
                }])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 2}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                return Result([])
            if "UPDATE courses SET" in sql:
                return Result([{
                    "id": 7, "schedule_id": 2, "name": "高数", "teacher": "张三",
                    "room": "A101", "weekday": 2, "start_section": 3, "end_section": 4,
                    "weeks": [1, 2, 3], "color": "#5B8DEF", "created_at": None
                }])
            if "UPDATE course_adjustments" in sql:
                self.adjustment_update = params
                return Result()
            if "INSERT INTO course_change_logs" in sql:
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    db = MockDb()
    monkeypatch.setattr("app.routers.courses.connect", lambda: db)
    course = CourseIn(
        schedule_id=2, name="高数", teacher="张三", room="A101",
        weekday=2, start_section=3, end_section=4, weeks=[1, 2, 3], color="#5B8DEF"
    )
    update_course(7, course, link_adjustments=True, user={"id": 1})
    # weekday delta: 2-1 = 1, start delta: 3-1 = 2, end delta: 4-2 = 2
    assert db.adjustment_update == (1, 2, 2, 7)


def test_edit_course_raises_conflict_if_linked_adjustment_collides(monkeypatch):
    class ConflictDb:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if "SELECT variant_type FROM schedules" in sql:
                return Result([{"variant_type": "adjusted"}])
            if "SELECT c.*,s.variant_type FROM courses c" in sql:
                return Result([{
                    "id": 7, "schedule_id": 2, "name": "高数", "teacher": "张三",
                    "room": "A101", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2, 3], "color": "#5B8DEF"
                }])
            if "SELECT * FROM course_adjustments" in sql:
                return Result([{
                    "id": 10, "course_id": 7, "week": 3, "weekday": 3,
                    "start_section": 5, "end_section": 6, "room": "B202"
                }])
            if "SELECT schedule_id FROM courses WHERE id=" in sql:
                return Result([{"schedule_id": 2}])
            if "FROM courses c LEFT JOIN course_adjustments" in sql:
                # 假设在目标星期4 第7-8节存在既有课程
                return Result([{
                    "id": 8, "schedule_id": 2, "name": "英语", "weekday": 4, "start_section": 7,
                    "end_section": 8, "weeks": [3], "adjusted_week": None, "adjusted_weekday": None,
                    "adjusted_start": None, "adjusted_end": None
                }])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("app.routers.courses.connect", lambda: ConflictDb())
    course = CourseIn(
        schedule_id=2, name="高数", teacher="张三", room="A101",
        weekday=2, start_section=3, end_section=4, weeks=[1, 2, 3], color="#5B8DEF"
    )
    with pytest.raises(HTTPException) as exc:
        update_course(7, course, link_adjustments=True, user={"id": 1})
    assert exc.value.status_code == 409
    assert "冲突" in exc.value.detail


def test_revoke_batch_adjustment_record(monkeypatch):
    class RevokeDb:
        def __init__(self):
            self.deleted_params = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if "SELECT l.* FROM course_change_logs" in sql:
                return Result([{
                    "id": 99,
                    "schedule_id": 1,
                    "details": [
                        {"course_id": 11, "week": 2},
                        {"course_id": 12, "week": 2},
                    ]
                }])
            if "DELETE FROM course_adjustments" in sql:
                self.deleted_params.append(params)
                return Result([{"id": 1}])
            raise AssertionError(f"Unexpected SQL: {sql}")

    db = RevokeDb()
    monkeypatch.setattr("app.routers.adjustments.connect", lambda: db)
    res = revoke_adjustment_record(99, user={"id": 1})
    assert res == {"revoked": 2, "total": 2}
    assert len(db.deleted_params) == 2


def test_match_extracted_building_prefix_completion(monkeypatch):
    class MatchDb:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if "SELECT 1 FROM schedules" in sql:
                return Result([{"1": 1}])
            if "SELECT * FROM courses" in sql:
                return Result([{
                    "id": 101, "schedule_id": 1, "name": "操作系统", "teacher": "李老师",
                    "room": "7-南201", "weekday": 1, "start_section": 1, "end_section": 2,
                    "weeks": [1, 2, 3], "color": "#5B8DEF"
                }])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr("app.routers.adjustments.connect", lambda: MatchDb())
    extracted = [{
        "course_name": "操作系统",
        "teacher": "李老师",
        "week": 2,
        "old_weekday": 1,
        "old_start_section": 1,
        "old_end_section": 2,
        "old_room": "",
        "new_weekday": 2,
        "new_start_section": 3,
        "new_end_section": 4,
        "new_room": "南312",  # 缺少楼栋前缀 7-
    }]
    result = match_extracted(1, 1, extracted)
    assert result["matched"] == 1
    item = result["items"][0]
    assert item["status"] == "matched"
    assert item["old_room"] == "7-南201"  # 自动回填原教室
    assert item["new_room"] == "7-南312"  # 自动补齐 7- 前缀
