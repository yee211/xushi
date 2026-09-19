from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.schedules import ScheduleUpdate, parse_schedule_date


def test_parse_schedule_date_valid():
    assert parse_schedule_date("2026-09-07", "测试日期") == date(2026, 9, 7)
    assert parse_schedule_date("", "测试日期") is None
    assert parse_schedule_date(None, "测试日期") is None

def test_parse_schedule_date_invalid():
    with pytest.raises(HTTPException) as exc_info:
        parse_schedule_date("not-a-date", "测试日期")
    assert exc_info.value.status_code == 400
    assert "YYYY-MM-DD" in exc_info.value.detail

def test_schedule_update_schema():
    payload = ScheduleUpdate(
        name="新课表",
        term="2026-2027学年第1学期",
        start_date="2026-09-07",
        end_date="2027-01-24"
    )
    assert payload.name == "新课表"
    assert payload.start_date == "2026-09-07"


def test_schedule_update_rejects_blank_name_and_cleans_term():
    with pytest.raises(ValidationError):
        ScheduleUpdate(name="   ")
    assert ScheduleUpdate(term="  2026 秋  ").term == "2026 秋"
