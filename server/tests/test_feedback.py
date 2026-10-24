"""Feedback persistence tests."""
from datetime import UTC, datetime

from app.rate_limit import SlidingWindowLimiter
from app.routers import feedback as main


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FeedbackDb:
    def __init__(self):
        self.insert_params = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        if "SELECT 1 FROM schedules" in sql:
            return Result({"?column?": 1})
        if "INSERT INTO feedbacks" in sql:
            self.insert_params = params
            return Result({"id": 12, "user_id": 7, "schedule_id": 3, "category": "import",
                           "description": params[3], "contact": params[4], "client_info": {},
                           "status": "pending", "created_at": datetime(2026, 9, 16, tzinfo=UTC)})
        raise AssertionError(sql)


def test_create_feedback_persists_and_returns_union_fields(monkeypatch):
    monkeypatch.setattr("app.rate_limit.get_redis", lambda: None)
    db = FeedbackDb()
    monkeypatch.setattr(main, "connect", lambda: db)
    monkeypatch.setattr(main, "feedback_limiter", SlidingWindowLimiter(3, 600))
    payload = main.FeedbackIn(category="import", description=" 导入后缺少两门课程 ", schedule_id=3)

    result = main.create_feedback(payload, user={"id": 7})

    assert db.insert_params[0:5] == (7, 3, "import", "导入后缺少两门课程", "")
    # 统一后端返回两端字段并集；小程序依赖的字段必须齐全
    assert result["id"] == 12
    assert result["feedback_no"] == "FB-20260916-000012"
    assert result["status"] == "pending"
