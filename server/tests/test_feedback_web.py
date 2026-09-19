"""Unit tests for feedback endpoint."""
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def test_submit_feedback(monkeypatch):
    class FeedbackDb:
        def __init__(self):
            self.inserted = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if "INSERT INTO feedback" in sql:
                self.inserted = params
                return Result({"id": 12, "created_at": None})
            raise AssertionError(f"Unexpected SQL: {sql}")

    db = FeedbackDb()
    monkeypatch.setattr("app.routers.feedback.connect", lambda: db)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "testuser", "email": "test@example.com"}

    client = TestClient(app)
    try:
        response = client.post(
            "/api/feedback",
            json={
                "category": "import",
                "description": "解析正方教务系统排课表报错",
                "contact": "test@qq.com",
                "client_info": {"platform": "Android", "app_version": "2.2.8"}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["feedback_id"] == 12
        assert "FB-" in data["feedback_number"]
        assert db.inserted[0] == 1
        # 合并后列序：user_id, schedule_id, category, description, contact, client_info
        assert db.inserted[1] is None
        assert db.inserted[2] == "import"
        assert db.inserted[3] == "解析正方教务系统排课表报错"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
