"""grounding 公共校验与新增盲区（教师姓名、具体日期）的行为单测。"""
import json
import sys
from datetime import date
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent import grounding, loop, polish_ai  # noqa: E402

COURSE = {"name": "高等数学", "start_time": "14:00", "end_time": "15:40", "teacher": "张华", "room": "A101"}


def day_fact(courses=None, date_str="2026-09-09"):
    return {"skill": "query_day_courses", "arguments": json.dumps({"date": date_str}),
            "result": {"date": date_str, "weekday": 3, "courses": [COURSE] if courses is None else courses}}


def test_hallucinated_teacher_with_suffix_rejected():
    facts = [day_fact()]
    assert not grounding.facts_grounded("明天 14:00 高数，是李雷老师教。", facts, "明天高数谁教", date(2026, 9, 8))
    assert grounding.facts_grounded("明天 14:00 高数，由张华老师带。", facts, "明天高数谁教", date(2026, 9, 8))


def test_teacher_mention_echoed_from_question_is_allowed():
    facts = [day_fact()]
    assert grounding.facts_grounded("语文老师布置的作业多，明天 14:00 有高等数学课。", facts,
                                    "我语文老师说明天有什么课", date(2026, 9, 8))


def test_hallucinated_dates_rejected_and_fact_dates_allowed():
    facts = [day_fact()]
    assert not grounding.facts_grounded("10月15日 14:00 有高等数学课。", facts, "明天有什么课", date(2026, 9, 8))
    assert not grounding.facts_grounded("2026-10-15 14:00 有高等数学课。", facts, "明天有什么课", date(2026, 9, 8))
    assert grounding.facts_grounded("9月9日 14:00 有高等数学课。", facts, "明天有什么课", date(2026, 9, 8))
    assert grounding.facts_grounded("2026-09-09 14:00 有高等数学课。", facts, "明天有什么课", date(2026, 9, 8))


def test_dates_grounded_allows_relative_and_question_echo():
    today = date(2026, 9, 8)
    assert grounding.dates_grounded("后天没有课", [], "后天有课吗", today)
    assert grounding.dates_grounded("查不到 2028-01-01 的课表", [], "2028-01-01有什么课", today)
    assert not grounding.dates_grounded("12月25日放假", [], "明天有什么课", today)


def test_loop_aliases_point_to_shared_grounding():
    assert loop._facts_grounded is grounding.facts_grounded
    assert loop._grounded is grounding.time_grounded
    assert polish_ai.TIME_PATTERN is grounding.TIME_PATTERN
    assert polish_ai.FORBIDDEN_TOKENS is grounding.FORBIDDEN_TOKENS
