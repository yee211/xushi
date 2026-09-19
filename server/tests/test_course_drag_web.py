from app.routers.courses import adjustment_conflicts


class FakeResult:
    def __init__(self, one=None, rows=None):
        self.one = one
        self.rows = rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, *_args):
        self.calls += 1
        return FakeResult(one={"schedule_id": 2}) if self.calls == 1 else FakeResult(rows=self.rows)


def test_adjustment_conflict_uses_effective_adjusted_position():
    db = FakeDb([{
        "weeks": [3], "weekday": 1, "start_section": 1, "end_section": 2,
        "adjusted_week": 3, "adjusted_weekday": 4, "adjusted_start": 5, "adjusted_end": 6,
    }])
    assert adjustment_conflicts(db, 1, 3, 4, 6, 7)


def test_adjustment_conflict_ignores_inactive_week():
    db = FakeDb([{
        "weeks": [4], "weekday": 4, "start_section": 5, "end_section": 6,
        "adjusted_week": None, "adjusted_weekday": None, "adjusted_start": None, "adjusted_end": None,
    }])
    assert not adjustment_conflicts(db, 1, 3, 4, 5, 6)
