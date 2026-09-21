"""Unit tests for the morning daily schedule and weather push feature."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.channels.weixin import worker  # noqa: E402
from app.services import daily_push  # noqa: E402
from app.services.daily_push import (  # noqa: E402
    build_morning_brief,
    build_weekly_early_class_notice,
    dispatch_morning_pushes,
    send_morning_push_to_user,
)
from app.services.schedule_query import ScheduleQueryError  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeDb:
    def __init__(self, query_results=None):
        self.query_results = query_results or {}
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        # Match table queries
        for pattern, result in self.query_results.items():
            if pattern in sql:
                if callable(result):
                    return FakeCursor(result(params))
                return FakeCursor(result)
        return FakeCursor([])


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.rowcount = len(rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeClient:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.sent_messages = []

    def send_text(self, to_user_id, text, context_token="", *, client_id, run_id=""):
        if self.should_fail:
            from app.channels.weixin.client import ILinkError
            raise ILinkError("network timeout")
        self.sent_messages.append({
            "to_user_id": to_user_id,
            "text": text,
            "context_token": context_token,
            "client_id": client_id,
        })

    def close(self):
        pass


def test_build_morning_brief_with_courses_and_rain(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_courses(db, user_id, target_date):
        return {
            "date": "2026-09-14",
            "weekday": 1,
            "week": 2,
            "courses": [
                {"start_time": "08:20", "end_time": "10:00", "name": "思政课", "room": "南204", "teacher": "杨老师"},
                {"start_time": "14:00", "end_time": "15:40", "name": "计算机网络", "room": "7-南312", "teacher": "龙老师"},
            ],
        }

    def fake_fetch_weather(target_date):
        return {
            "condition": "中雨",
            "temp_min": 20,
            "temp_max": 25,
            "rain": True,
            "rain_probability": 80,
        }

    monkeypatch.setattr(daily_push, "query_courses_by_date", fake_query_courses)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", fake_fetch_weather)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "【今日课表与天气】" in brief
    assert "2026年9月14日 星期一（第2周）" in brief
    assert "天气：中雨，20℃ ~ 25℃" in brief
    assert "☔ 提醒：今天有降雨（概率 80%），出门记得带伞！" in brief
    assert "📚 今日课程（共 2 门）：" in brief
    assert "1. 08:20-10:00 思政课 @ 南204 · 杨老师" in brief
    assert "2. 14:00-15:40 计算机网络 @ 7-南312 · 龙老师" in brief


def test_build_morning_brief_with_courses_no_rain(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_courses(db, user_id, target_date):
        return {
            "date": "2026-09-14",
            "weekday": 1,
            "week": 2,
            "courses": [
                {"start_time": "08:20", "end_time": "10:00", "name": "高数", "room": "教101", "teacher": None},
            ],
        }

    def fake_fetch_weather(target_date):
        return {
            "condition": "晴",
            "temp_min": 22,
            "temp_max": 31,
            "rain": False,
            "rain_probability": 0,
        }

    monkeypatch.setattr(daily_push, "query_courses_by_date", fake_query_courses)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", fake_fetch_weather)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "天气：晴，22℃ ~ 31℃" in brief
    assert "带伞" not in brief
    assert "1. 08:20-10:00 高数 @ 教101" in brief


def test_build_morning_brief_no_courses(monkeypatch):
    test_date = date(2026, 9, 20)

    def fake_query_courses(db, user_id, target_date):
        return {"date": "2026-09-20", "weekday": 7, "week": 2, "courses": []}

    def fake_fetch_weather(target_date):
        return {
            "condition": "多云",
            "temp_min": 19,
            "temp_max": 27,
            "rain": False,
            "rain_probability": 10,
        }

    monkeypatch.setattr(daily_push, "query_courses_by_date", fake_query_courses)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", fake_fetch_weather)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "🎉 今日无课，好好休息！" in brief
    assert "带伞" not in brief


def test_send_morning_push_to_user_success(monkeypatch):
    test_date = date(2026, 9, 14)
    db = FakeDb()
    client = FakeClient()

    monkeypatch.setattr(daily_push, "query_courses_by_date", lambda db, u, d: {"courses": []})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    ok = send_morning_push_to_user(db, client, 1, "wx_user_1", "token123", test_date)
    assert ok is True
    assert len(client.sent_messages) == 1
    assert client.sent_messages[0]["to_user_id"] == "wx_user_1"
    assert client.sent_messages[0]["context_token"] == "token123"

    # Verify DB recorded success
    sql_executed = [item[0] for item in db.executed]
    assert any("INSERT INTO daily_push_logs" in s for s in sql_executed)


def test_send_morning_push_to_user_ilink_rejection_is_terminal(monkeypatch):
    """iLink 业务拒绝（如 -2 prepare failed）记为 skipped，当天不再重试。"""
    test_date = date(2026, 9, 14)
    db = FakeDb()
    client = FakeClient(should_fail=True)

    monkeypatch.setattr(daily_push, "query_courses_by_date", lambda db, u, d: {"courses": []})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    ok = send_morning_push_to_user(db, client, 1, "wx_user_1", "token123", test_date)
    assert ok is False

    params = [item[1] for item in db.executed if "INSERT INTO daily_push_logs" in item[0]]
    assert params and params[0][2] == "skipped"
    assert "network timeout" in params[0][3]


def test_send_morning_push_to_user_transport_error_propagates(monkeypatch):
    """非 ILinkError（网络抖动等）必须抛给调用方，由其记 failed 以便窗口内重试。"""
    db = FakeDb()

    class TimeoutClient(FakeClient):
        def send_text(self, *args, **kwargs):
            raise TimeoutError("connection reset")

    monkeypatch.setattr(daily_push, "query_courses_by_date", lambda db, u, d: {"courses": []})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    with pytest.raises(TimeoutError):
        send_morning_push_to_user(db, TimeoutClient(), 1, "wx_user_1", "t", date(2026, 9, 14))
    assert not [item for item in db.executed if "INSERT INTO daily_push_logs" in item[0]]


def test_dispatch_isolates_per_user_crash(monkeypatch):
    """单个用户抛异常不得中断整批：排在其后的用户仍要收到晨报。"""
    from app.channels.weixin.protocol import Credentials

    rows = [
        {"user_id": 1, "provider_user_id": "u1", "context_token": "c1", "account_id": "bot1"},
        {"user_id": 2, "provider_user_id": "u2", "context_token": "c2", "account_id": "bot1"},
        {"user_id": 3, "provider_user_id": "u3", "context_token": "c3", "account_id": "bot1"},
    ]
    db = FakeDb({"SELECT u.user_id": rows})
    client = FakeClient()

    def query_courses(_db, user_id, _target_date):
        if user_id == 2:
            raise RuntimeError("connection lost mid-batch")
        return {"courses": []}

    monkeypatch.setattr(daily_push, "load_accounts",
                        lambda db: [(Credentials("bot1", "token1", "http://one"), "", "")])
    monkeypatch.setattr(daily_push, "ILinkClient", lambda cred: client)
    monkeypatch.setattr(daily_push, "query_courses_by_date", query_courses)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    sent = dispatch_morning_pushes(db, date(2026, 9, 14))

    assert sent == 2
    assert [m["to_user_id"] for m in client.sent_messages] == ["u1", "u3"]
    statuses = [item[1] for item in db.executed if "INSERT INTO daily_push_logs" in item[0]]
    assert [s[2] for s in statuses] == ["done", "failed", "done"]


def test_dispatch_skips_user_without_credentials(monkeypatch):
    """账号凭证缺失时记 skipped 而非静默 continue，避免永久 pending 触发全天重试。"""
    rows = [{"user_id": 7, "provider_user_id": "u7", "context_token": "c7", "account_id": "ghost"}]
    db = FakeDb({"SELECT u.user_id": rows})
    monkeypatch.setattr(daily_push, "load_accounts", lambda db: [])

    assert dispatch_morning_pushes(db, date(2026, 9, 14)) == 0
    params = [item[1] for item in db.executed if "INSERT INTO daily_push_logs" in item[0]]
    assert params and params[0][2] == "skipped"


def test_dispatch_morning_pushes_idempotency(monkeypatch):
    test_date = date(2026, 9, 14)
    client = FakeClient()
    from app.channels.weixin.protocol import Credentials

    # Setup: 1 pending user initially
    pending_users = [{"user_id": 1, "provider_user_id": "u1", "context_token": "ctx",
                      "account_id": "bot1", "bot_token_encrypted": "x",
                      "api_base_url": "http://base", "admin_user_id": ""}]

    def handle_query(params):
        return pending_users

    db = FakeDb({"SELECT u.user_id": handle_query})
    monkeypatch.setattr(daily_push, "load_accounts", lambda db: [(Credentials("bot1", "token", "http://base"), "", "")])
    monkeypatch.setattr(daily_push, "ILinkClient", lambda cred: client)
    monkeypatch.setattr(daily_push, "query_courses_by_date", lambda db, u, d: {"courses": []})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    sent = dispatch_morning_pushes(db, test_date)
    assert sent == 1
    assert len(client.sent_messages) == 1

    # Second run: user now excluded by LEFT JOIN daily_push_logs
    pending_users.clear()
    sent_second = dispatch_morning_pushes(db, test_date)
    assert sent_second == 0
    assert len(client.sent_messages) == 1


def test_dispatch_uses_matching_account_for_each_user(monkeypatch):
    from app.channels.weixin.protocol import Credentials

    rows = [
        {"user_id": 1, "provider_user_id": "u1", "context_token": "c1", "account_id": "bot1"},
        {"user_id": 2, "provider_user_id": "u2", "context_token": "c2", "account_id": "bot2"},
    ]
    db = FakeDb({"SELECT u.user_id": rows})
    clients = {}

    def make_client(credentials):
        client = FakeClient()
        clients[credentials.account_id] = client
        return client

    monkeypatch.setattr(daily_push, "load_accounts", lambda db: [
        (Credentials("bot1", "token1", "http://one"), "", ""),
        (Credentials("bot2", "token2", "http://two"), "", ""),
    ])
    monkeypatch.setattr(daily_push, "ILinkClient", make_client)
    monkeypatch.setattr(daily_push, "query_courses_by_date", lambda db, u, d: {"courses": []})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    assert dispatch_morning_pushes(db, date(2026, 9, 14)) == 2
    assert clients["bot1"].sent_messages[0]["to_user_id"] == "u1"
    assert clients["bot2"].sent_messages[0]["to_user_id"] == "u2"


def test_build_weekly_early_class_notice_zero_days(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 3, "start_time": "10:20"}]},
                {"weekday": 2, "courses": [{"start_section": 5, "start_time": "14:00"}]},
                {"weekday": 3, "courses": []},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": []},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "🎉 本周福利：全周无早八，每天都可以多睡一会儿！"


def test_build_weekly_early_class_notice_one_day(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": []},
                {"weekday": 2, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 3, "courses": [{"start_section": 3, "start_time": "10:20"}]},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": []},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "☕ 本周早八：仅 1 天（周二），节奏很轻松~"


def test_build_weekly_early_class_notice_two_days(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": []},
                {"weekday": 2, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 3, "courses": []},
                {"weekday": 4, "courses": [{"start_section": 1, "start_time": "08:00"}]},
                {"weekday": 5, "courses": []},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "☕ 本周早八：共 2 天（周二、周四），节奏很轻松~"


def test_build_weekly_early_class_notice_three_and_four_days(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week_3(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": []},
                {"weekday": 3, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week_3)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "⏰ 本周早八预警：共 3 天（周一、周三、周五），注意保持规律作息！"

    def fake_query_week_4(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 3, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week_4)
    notice4 = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice4 == "⏰ 本周早八预警：共 4 天（周一、周二、周三、周五），注意保持规律作息！"


def test_build_weekly_early_class_notice_five_workdays(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 3, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 4, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 5, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "🔋 本周高能：周一至周五全满早八（5天），上好闹钟，今晚早点睡！"


def test_build_weekly_early_class_notice_with_weekend(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": []},
                {"weekday": 3, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 6, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == "⏰ 本周早八预警：共 4 天（周一、周三、周五、周六），注意保持规律作息！"


def test_build_weekly_early_class_notice_exception_handled(monkeypatch):
    test_date = date(2026, 9, 14)

    def fake_query_error(db, user_id, anchor_date):
        raise RuntimeError("db connection lost")

    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_error)
    notice = build_weekly_early_class_notice(FakeDb(), 1, test_date)
    assert notice == ""


def test_build_morning_brief_on_monday_includes_early_notice(monkeypatch):
    test_date = date(2026, 9, 14)  # Monday

    def fake_query_courses(db, user_id, target_date):
        return {
            "date": "2026-09-14",
            "weekday": 1,
            "week": 3,
            "courses": [
                {"start_time": "08:20", "end_time": "10:00", "name": "高数", "room": "教101", "teacher": "李老师"},
            ],
        }

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": []},
                {"weekday": 3, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 4, "courses": []},
                {"weekday": 5, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 6, "courses": []},
                {"weekday": 7, "courses": []},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_date", fake_query_courses)
    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "⏰ 本周早八预警：共 3 天（周一、周三、周五）" in brief
    assert "📚 今日课程（共 1 门）：" in brief


def test_build_morning_brief_on_tuesday_excludes_early_notice(monkeypatch):
    test_date = date(2026, 9, 15)  # Tuesday

    def fake_query_courses(db, user_id, target_date):
        return {
            "date": "2026-09-15",
            "weekday": 2,
            "week": 3,
            "courses": [
                {"start_time": "08:20", "end_time": "10:00", "name": "高数", "room": "教101", "teacher": "李老师"},
            ],
        }

    def fake_query_week(db, user_id, anchor_date):
        return {
            "days": [
                {"weekday": 1, "courses": [{"start_section": 1, "start_time": "08:20"}]},
                {"weekday": 2, "courses": [{"start_section": 1, "start_time": "08:20"}]},
            ]
        }

    monkeypatch.setattr(daily_push, "query_courses_by_date", fake_query_courses)
    monkeypatch.setattr(daily_push, "query_courses_by_week", fake_query_week)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "本周早八" not in brief
    assert "📚 今日课程（共 1 门）：" in brief


def test_build_morning_brief_outside_term_degrades_gracefully(monkeypatch):
    """假期/学期外：真实的 query_courses_by_date 会抛 OUTSIDE_TERM（不是返回 week=None），
    晨报必须降级成「今日无课」而不是把异常抛出去中断整批推送。"""
    test_date = date(2026, 9, 14)  # Monday

    def raise_outside_term(db, user_id, target_date):
        raise ScheduleQueryError("OUTSIDE_TERM", "目标日期不在任何课表的学期范围内")

    monkeypatch.setattr(daily_push, "query_courses_by_date", raise_outside_term)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    brief = build_morning_brief(FakeDb(), 1, test_date)

    assert "🎉 今日无课，好好休息！" in brief
    assert "本周早八" not in brief
    assert "2026年9月14日 星期一" in brief


def test_build_morning_brief_ambiguous_schedule_tells_user_to_pick(monkeypatch):
    """多张生效课表时不能谎报「今日无课」，要提示用户去选默认课表。"""
    def raise_ambiguous(db, user_id, target_date):
        raise ScheduleQueryError("AMBIGUOUS_SCHEDULE", "目标日期存在多张可用课表，请先选择默认课表")

    monkeypatch.setattr(daily_push, "query_courses_by_date", raise_ambiguous)
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    brief = build_morning_brief(FakeDb(), 1, date(2026, 9, 14))

    assert "多张生效中的课表" in brief
    assert "今日无课" not in brief


def test_build_morning_brief_survives_incomplete_course_row(monkeypatch):
    """课程行缺字段时不得抛 KeyError（会中断整批推送）。"""
    monkeypatch.setattr(daily_push, "query_courses_by_date",
                        lambda db, u, d: {"week": 2, "courses": [{"room": "教101"}, {"name": "高数"}]})
    monkeypatch.setattr(daily_push, "fetch_daily_weather", lambda d: None)

    brief = build_morning_brief(FakeDb(), 1, date(2026, 9, 15))

    assert "1. 未命名课程 @ 教101" in brief
    assert "2. 高数" in brief


class _FixedDatetime(datetime):
    """让 worker.check_morning_push 读到固定的「当前时间」。"""
    fixed: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


class _ConnCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _freeze(monkeypatch, when: datetime) -> None:
    _FixedDatetime.fixed = when
    monkeypatch.setattr(worker, "datetime", _FixedDatetime)
    monkeypatch.setattr(worker, "connect", lambda: _ConnCtx())
    monkeypatch.setattr(worker, "_last_push_date", None)
    monkeypatch.setenv("MORNING_PUSH_ENABLED", "true")
    monkeypatch.setenv("MORNING_PUSH_TIME", "07:30")
    monkeypatch.setenv("MORNING_PUSH_RETRY_WINDOW_MINUTES", "180")
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")


def test_morning_push_window_defaults(monkeypatch):
    monkeypatch.delenv("MORNING_PUSH_TIME", raising=False)
    monkeypatch.delenv("MORNING_PUSH_RETRY_WINDOW_MINUTES", raising=False)
    start, deadline = worker._morning_push_window(datetime(2026, 9, 21, 12, 0, tzinfo=SHANGHAI))
    assert (start.hour, start.minute) == (7, 30)
    assert deadline - start == timedelta(minutes=180)


def test_morning_push_window_rejects_garbage(monkeypatch):
    monkeypatch.setenv("MORNING_PUSH_TIME", "25:99")
    monkeypatch.setenv("MORNING_PUSH_RETRY_WINDOW_MINUTES", "abc")
    start, deadline = worker._morning_push_window(datetime(2026, 9, 21, 12, 0, tzinfo=SHANGHAI))
    assert (start.hour, start.minute) == (7, 30)
    assert deadline - start == timedelta(minutes=180)


def test_check_morning_push_waits_before_start(monkeypatch):
    dispatched = []
    _freeze(monkeypatch, datetime(2026, 9, 21, 6, 0, tzinfo=SHANGHAI))
    monkeypatch.setattr(daily_push, "dispatch_morning_pushes", lambda *a: dispatched.append(a) or 0)

    worker.check_morning_push()

    assert not dispatched
    assert worker._last_push_date is None


def test_check_morning_push_retries_while_pending_inside_window(monkeypatch):
    dispatched = []
    _freeze(monkeypatch, datetime(2026, 9, 21, 8, 0, tzinfo=SHANGHAI))
    monkeypatch.setattr(daily_push, "dispatch_morning_pushes", lambda *a: dispatched.append(a) or 0)
    monkeypatch.setattr(daily_push, "pending_morning_push_count", lambda db, d: 1)

    worker.check_morning_push()

    assert len(dispatched) == 1
    assert worker._last_push_date is None


def test_check_morning_push_stops_when_all_done(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 21, 8, 0, tzinfo=SHANGHAI))
    monkeypatch.setattr(daily_push, "dispatch_morning_pushes", lambda *a: 3)
    monkeypatch.setattr(daily_push, "pending_morning_push_count", lambda db, d: 0)

    worker.check_morning_push()

    assert worker._last_push_date == date(2026, 9, 21)


def test_check_morning_push_gives_up_after_window(monkeypatch):
    """窗口关闭后既不补发迟到的晨报，也不再每 10 秒重试一整天。"""
    dispatched = []
    _freeze(monkeypatch, datetime(2026, 9, 21, 15, 0, tzinfo=SHANGHAI))
    monkeypatch.setattr(daily_push, "dispatch_morning_pushes", lambda *a: dispatched.append(a) or 0)
    monkeypatch.setattr(daily_push, "pending_morning_push_count", lambda db, d: 1)

    worker.check_morning_push()

    assert not dispatched
    assert worker._last_push_date == date(2026, 9, 21)


def test_check_morning_push_disabled(monkeypatch):
    dispatched = []
    _freeze(monkeypatch, datetime(2026, 9, 21, 8, 0, tzinfo=SHANGHAI))
    monkeypatch.setenv("MORNING_PUSH_ENABLED", "false")
    monkeypatch.setattr(daily_push, "dispatch_morning_pushes", lambda *a: dispatched.append(a) or 0)

    worker.check_morning_push()

    assert not dispatched

