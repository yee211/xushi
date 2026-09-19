"""接口层单测：模型校验、图片签名、调课匹配、限流。不依赖数据库。"""
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from pydantic import ValidationError  # noqa: E402

from app.rate_limit import SlidingWindowLimiter  # noqa: E402
from app.routers.adjustments import match_course, normalized, valid_image_signature  # noqa: E402
from app.schemas import CourseIn  # noqa: E402
from app.settings import validate_settings  # noqa: E402


def test_course_in_strips_and_validates_color():
    course = CourseIn(schedule_id=1, name="  高等数学  ", teacher=" 张三 ", weekday=1,
                      start_section=1, end_section=2, color="#5B8DEF")
    assert course.name == "高等数学" and course.teacher == "张三"
    with pytest.raises(ValidationError):
        CourseIn(schedule_id=1, name="x", weekday=1, start_section=1, end_section=2, color="blue")
    with pytest.raises(ValidationError):
        CourseIn(schedule_id=0, name="x", weekday=1, start_section=1, end_section=2)


def test_valid_image_signature(make_file):
    png = make_file("fixture.png", b"\x89PNG\r\n\x1a\npayload")
    assert valid_image_signature(png.read_bytes(), "image/png") is True
    assert valid_image_signature(b"\xff\xd8\xff\xe0payload", "image/jpeg") is True
    assert valid_image_signature(b"RIFF1234WEBPVP8", "image/webp") is True
    assert valid_image_signature(b"GIF89a", "image/png") is False


def test_match_course_normalization():
    courses = [
        {"weekday": 1, "start_section": 1, "end_section": 2, "weeks": [3], "name": "高等数学", "teacher": "张三", "id": 11},
        {"weekday": 1, "start_section": 1, "end_section": 2, "weeks": [3], "name": "高等数学（甲）", "teacher": "李四", "id": 12},
    ]
    item = {"course_name": "高等 数学", "teacher": "张三", "old_weekday": 1, "old_start_section": 1,
            "old_end_section": 2, "week": 3}
    matched, count = match_course(courses, item)
    assert matched["id"] == 11 and count == 1
    ambiguous, count2 = match_course(courses, {**item, "teacher": ""})
    assert ambiguous is None and count2 == 2
    none, count3 = match_course(courses, {**item, "old_weekday": 5})
    assert none is None and count3 == 0


def test_normalized_strips_noise():
    assert normalized("高等 数学（一）-2026") == "高等数学一2026"


def test_login_limiter_window():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.hit("1.2.3.4")[0] is True
    assert limiter.hit("1.2.3.4")[0] is True
    allowed, retry_after = limiter.hit("1.2.3.4")
    assert allowed is False and retry_after >= 1
    assert limiter.hit("5.6.7.8")[0] is True


def test_settings_default_to_production_safety(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("WECHAT_DEV_OPENID", "local-dev-user")
    monkeypatch.setenv("WECHAT_APP_ID", "wx-test")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    with pytest.raises(RuntimeError, match="WECHAT_DEV_OPENID"):
        validate_settings()


def test_settings_allow_explicit_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WECHAT_DEV_OPENID", "local-dev-user")
    validate_settings()
