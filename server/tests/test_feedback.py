"""Feedback persistence and enterprise WeChat notification tests."""
from datetime import UTC, datetime

from fastapi import BackgroundTasks

from app.rate_limit import SlidingWindowLimiter
from app.routers import feedback as main
from app.services import feedback as feedback_service


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


def test_create_feedback_persists_then_queues_notification(monkeypatch):
    db = FeedbackDb()
    queued = []
    tasks = BackgroundTasks()
    monkeypatch.setattr(main, "connect", lambda: db)
    monkeypatch.setattr(main, "feedback_limiter", SlidingWindowLimiter(3, 600))
    monkeypatch.setattr(tasks, "add_task", lambda function, item: queued.append((function, item)))
    payload = main.FeedbackIn(category="import", description=" 导入后缺少两门课程 ", schedule_id=3)

    result = main.create_feedback(payload, tasks, user={"id": 7})

    assert db.insert_params[0:5] == (7, 3, "import", "导入后缺少两门课程", "")
    # 统一后端返回两端字段并集；小程序依赖的字段必须齐全
    assert result["id"] == 12
    assert result["feedback_no"] == "FB-20260916-000012"
    assert result["status"] == "pending"
    assert queued[0][0] is main.send_feedback_notification


def test_notification_posts_markdown_without_exposing_user_id(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 0}

    monkeypatch.setenv("WECOM_FEEDBACK_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setenv("FEEDBACK_ANON_SALT", "test-salt")
    monkeypatch.setattr(feedback_service.httpx, "post",
                        lambda url, **kwargs: captured.update(url=url, **kwargs) or Response())
    item = {"id": 12, "user_id": 7, "category": "import", "description": "课表缺失",
            "created_at": "2026-09-16T08:00:00+00:00",
            "client_info": {"platform": "android", "system": "Android 16", "wechat_version": "8.0"}}

    assert feedback_service.send_feedback_notification(item) is True
    content = captured["json"]["markdown"]["content"]
    assert "FB-20260916-000012" in content and "课表缺失" in content
    assert "用户：7" not in content


def test_notification_is_disabled_without_webhook(monkeypatch):
    monkeypatch.delenv("WECOM_FEEDBACK_WEBHOOK_URL", raising=False)
    assert feedback_service.send_feedback_notification({}) is False
