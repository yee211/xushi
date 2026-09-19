"""Agent 相关测试共享的假数据库与数据构造器。

FakeAgentDb 按 SQL 关键字路由（与真实 psycopg 无关），覆盖绑定码消费、身份映射、
课表查询三类语句，并记录关键参数供断言（如 schedules 查询注入的 user_id）。
"""
from datetime import date, timedelta

from app.services.schedule_query import teaching_week


class FakeResult:
    def __init__(self, rows, rowcount=None):
        self._rows, self.rowcount = rows, len(rows) if rowcount is None else rowcount

    def fetchone(self): return self._rows[0] if self._rows else None
    def fetchall(self): return self._rows


class FakeAgentDb:
    def __init__(self, binding_row=None, identity_user_id=None, schedules=(), courses=(), delete_rowcount=0,
                 identity_rows=None):
        self.binding_row, self.identity_user_id = binding_row, identity_user_id
        self.schedules, self.courses, self.delete_rowcount = schedules, courses, delete_rowcount
        self.identity_rows = identity_rows
        self.inserted_identities, self.consumed_codes, self.generated_codes = [], [], []
        self.schedule_query_user_ids = []

    def execute(self, sql, params=None):
        if "FROM identity_binding_codes" in sql and "FOR UPDATE" in sql:
            return FakeResult([self.binding_row] if self.binding_row else [])
        if sql.startswith("UPDATE identity_binding_codes"):
            self.consumed_codes.append(params)
            return FakeResult([])
        if sql.startswith("INSERT INTO identity_binding_codes"):
            self.generated_codes.append(params)
            return FakeResult([{"id": 1}])
        if sql.startswith("SELECT") and "FROM user_identities" in sql:
            if self.identity_rows is not None:
                return FakeResult(self.identity_rows)
            if self.identity_user_id is None:
                return FakeResult([])
            return FakeResult([{"user_id": self.identity_user_id}])
        if sql.startswith("UPDATE user_identities"):
            return FakeResult([])
        if sql.startswith("DELETE FROM user_identities"):
            return FakeResult([], rowcount=self.delete_rowcount)
        if sql.startswith("INSERT INTO user_identities"):
            self.inserted_identities.append(params)
            return FakeResult([])
        if "FROM schedules" in sql:
            self.schedule_query_user_ids.append(params[0])
            return FakeResult([item for item in self.schedules if teaching_week(item, params[1]) is not None])
        if "FROM courses" in sql:
            return FakeResult(self.courses)
        if "FROM course_adjustments" in sql:
            return FakeResult([])
        raise AssertionError(sql)

    def __enter__(self): return self

    def __exit__(self, *args): return False


def today_schedule():
    today = date.today()
    return {"id": 1, "name": "测试课表", "term": "2026-2027-1", "start_date": today - timedelta(days=30),
            "end_date": today + timedelta(days=60), "variant_type": "original", "source_schedule_id": None}


def wednesday_course():
    return {"id": 11, "name": "高数", "teacher": "张老师", "room": "A101", "weekday": 3,
            "start_section": 5, "end_section": 6, "weeks": []}


def next_wednesday():
    today = date.today()
    return today + timedelta(days=(3 - today.isoweekday()) % 7)
