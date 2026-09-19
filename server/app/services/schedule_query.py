"""Deterministic timetable queries shared by HTTP endpoints and Agent tools."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

APP_TIMEZONE = "Asia/Shanghai"

@dataclass(frozen=True)
class SectionTime:
    number: int
    start: time
    end: time

SECTION_TIMES = (
    SectionTime(1, time(8, 20), time(9, 5)), SectionTime(2, time(9, 15), time(10, 0)),
    SectionTime(3, time(10, 20), time(11, 5)), SectionTime(4, time(11, 15), time(12, 0)),
    SectionTime(5, time(14, 0), time(14, 45)), SectionTime(6, time(14, 55), time(15, 40)),
    SectionTime(7, time(16, 0), time(16, 45)), SectionTime(8, time(16, 55), time(17, 40)),
    SectionTime(9, time(19, 0), time(19, 45)), SectionTime(10, time(19, 55), time(20, 40)),
    SectionTime(11, time(20, 50), time(21, 35)), SectionTime(12, time(21, 45), time(22, 30)),
)
SECTION_BY_NUMBER = {item.number: item for item in SECTION_TIMES}
PERIOD_SECTIONS = {"all": (1, 12), "morning": (1, 4), "afternoon": (5, 8), "evening": (9, 12)}

class ScheduleQueryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])

def teaching_week(schedule: Mapping, target_date: date) -> int | None:
    """Return a 1-based teaching week, or None when outside the term."""
    start, end = _as_date(schedule.get("start_date")), _as_date(schedule.get("end_date"))
    if not start or target_date < start or (end and target_date > end):
        return None
    week = (target_date - start).days // 7 + 1
    return week if 1 <= week <= 30 else None

def select_effective_schedule(schedules: Sequence[Mapping], target_date: date,
                              default_schedule_id: int | None = None) -> Mapping:
    """Select an active schedule, preferring an adjusted copy over its source."""
    active = [item for item in schedules if teaching_week(item, target_date) is not None]
    if not active:
        raise ScheduleQueryError("OUTSIDE_TERM", "目标日期不在任何课表的学期范围内")
    effective = [item for item in active if not (
        item.get("variant_type") == "original" and any(
            candidate.get("variant_type") == "adjusted" and candidate.get("source_schedule_id") == item["id"]
            for candidate in active))]
    if default_schedule_id is not None:
        chosen = next((item for item in active if int(item["id"]) == int(default_schedule_id)), None)
        if chosen:
            adjusted = next((item for item in effective if item.get("source_schedule_id") == chosen["id"]), None)
            return adjusted or chosen
    if len(effective) == 1:
        return effective[0]
    raise ScheduleQueryError("AMBIGUOUS_SCHEDULE", "目标日期存在多张可用课表，请先选择默认课表")

def materialize_courses(courses: Iterable[Mapping], adjustments: Iterable[Mapping],
                        week: int, weekday: int, period: str = "all") -> list[dict]:
    """Apply weekly overrides before filtering on final weekday and period."""
    if weekday not in range(1, 8):
        raise ScheduleQueryError("INVALID_DATE", "星期必须在 1 到 7 之间")
    if period not in PERIOD_SECTIONS:
        raise ScheduleQueryError("INVALID_PERIOD", "无效的时间段")
    overrides = {int(item["course_id"]): item for item in adjustments if int(item["week"]) == week}
    period_start, period_end = PERIOD_SECTIONS[period]
    result = []
    for source in courses:
        weeks = source.get("weeks") or []
        if weeks and week not in weeks:
            continue
        item, override = dict(source), overrides.get(int(source["id"]))
        if override:
            item.update(weekday=override["weekday"], start_section=override["start_section"],
                        end_section=override["end_section"], room=override.get("room") or item.get("room") or "",
                        adjusted=True, adjusted_week=week)
        else:
            item.update(adjusted=False, adjusted_week=None)
        start, end = int(item["start_section"]), int(item["end_section"])
        if int(item["weekday"]) != weekday or end < period_start or start > period_end:
            continue
        if start not in SECTION_BY_NUMBER or end not in SECTION_BY_NUMBER:
            raise ScheduleQueryError("INVALID_SECTION", "课程节次不在 1 到 12 之间")
        item["start_time"] = SECTION_BY_NUMBER[start].start.strftime("%H:%M")
        item["end_time"] = SECTION_BY_NUMBER[end].end.strftime("%H:%M")
        result.append(item)
    return sorted(result, key=lambda item: (item["start_section"], item["end_section"], item["name"]))

def query_courses_by_date(db, user_id: int, target_date: date, period: str = "all",
                          default_schedule_id: int | None = None) -> dict:
    schedules = db.execute("""SELECT * FROM schedules WHERE user_id=%s AND start_date IS NOT NULL
        AND start_date<=%s AND (end_date IS NULL OR end_date>=%s) ORDER BY id DESC""",
        (user_id, target_date, target_date)).fetchall()
    schedule = select_effective_schedule(schedules, target_date, default_schedule_id)
    week = teaching_week(schedule, target_date)
    courses = db.execute("SELECT * FROM courses WHERE schedule_id=%s ORDER BY weekday,start_section,id",
                         (schedule["id"],)).fetchall()
    ids, adjustments = [item["id"] for item in courses], []
    if ids:
        adjustments = db.execute("SELECT * FROM course_adjustments WHERE course_id=ANY(%s) AND week=%s",
                                 (ids, week)).fetchall()
    return {"date": target_date.isoformat(), "weekday": target_date.isoweekday(), "week": week,
            "schedule_id": schedule["id"], "schedule_name": schedule.get("term") or schedule.get("name") or "课表",
            "timezone": APP_TIMEZONE,
            "courses": materialize_courses(courses, adjustments, week, target_date.isoweekday(), period)}

def next_course(db, user_id: int, now: datetime | None = None, lookahead_days: int = 7,
                default_schedule_id: int | None = None) -> dict:
    timezone = ZoneInfo(APP_TIMEZONE)
    current = now.astimezone(timezone) if now and now.tzinfo else (
        now.replace(tzinfo=timezone) if now else datetime.now(timezone))
    for offset in range(max(0, min(int(lookahead_days), 30)) + 1):
        target = current.date() + timedelta(days=offset)
        try:
            result = query_courses_by_date(db, user_id, target, "all", default_schedule_id)
        except ScheduleQueryError as error:
            if error.code == "OUTSIDE_TERM":
                continue
            raise
        for course in result["courses"]:
            starts = datetime.combine(target, SECTION_BY_NUMBER[course["start_section"]].start, timezone)
            ends = datetime.combine(target, SECTION_BY_NUMBER[course["end_section"]].end, timezone)
            if ends < current:
                continue
            return {**result, "course": course, "status": "ongoing" if starts <= current <= ends else "upcoming"}
    return {"course": None, "status": "none", "timezone": APP_TIMEZONE}

def query_courses_by_week(db, user_id: int, anchor_date: date,
                          weekday: int | None = None,
                          default_schedule_id: int | None = None) -> dict:
    """Return one natural Monday-Sunday week, optionally narrowed to a weekday."""
    if weekday is not None and weekday not in range(1, 8):
        raise ScheduleQueryError("INVALID_DATE", "星期必须在 1 到 7 之间")
    monday = anchor_date - timedelta(days=anchor_date.isoweekday() - 1)
    offsets = [weekday - 1] if weekday else list(range(7))
    days = []
    for offset in offsets:
        target = monday + timedelta(days=offset)
        try:
            result = query_courses_by_date(db, user_id, target, "all", default_schedule_id)
        except ScheduleQueryError as error:
            if error.code == "OUTSIDE_TERM":
                days.append({"date": target.isoformat(), "weekday": target.isoweekday(), "courses": []})
                continue
            raise
        days.append(result)
    return {"week_start": monday.isoformat(), "week_end": (monday + timedelta(days=6)).isoformat(),
            "timezone": APP_TIMEZONE, "days": days}

def find_course(db, user_id: int, course_name: str, from_date: date,
                days: int = 30, default_schedule_id: int | None = None) -> dict:
    """Find upcoming occurrences by a conservative normalized name match."""
    needle = "".join(str(course_name or "").lower().split())
    if not needle:
        raise ScheduleQueryError("INVALID_COURSE_NAME", "课程名称不能为空")
    occurrences, seen = [], set()
    for offset in range(max(1, min(int(days), 90))):
        target = from_date + timedelta(days=offset)
        try:
            result = query_courses_by_date(db, user_id, target, "all", default_schedule_id)
        except ScheduleQueryError as error:
            if error.code == "OUTSIDE_TERM":
                continue
            raise
        for item in result["courses"]:
            haystack = "".join(str(item.get("name") or "").lower().split())
            if needle not in haystack and haystack not in needle:
                continue
            key = (target, item["id"], item["start_section"], item["end_section"])
            if key in seen:
                continue
            seen.add(key)
            occurrences.append({**item, "date": target.isoformat(), "week": result["week"]})
    names = sorted({item["name"] for item in occurrences})
    if len(names) > 1:
        raise ScheduleQueryError("AMBIGUOUS_COURSE", f"匹配到多门课程：{'、'.join(names)}")
    return {"query": course_name, "from_date": from_date.isoformat(), "days": days,
            "timezone": APP_TIMEZONE, "occurrences": occurrences}


def list_course_catalog(db, user_id: int, target_date: date,
                        default_schedule_id: int | None = None) -> list[dict]:
    """Return unique course candidates from this user's effective schedule."""
    schedules = db.execute("""SELECT * FROM schedules WHERE user_id=%s AND start_date IS NOT NULL
        AND start_date<=%s AND (end_date IS NULL OR end_date>=%s) ORDER BY id DESC""",
        (user_id, target_date, target_date)).fetchall()
    schedule = select_effective_schedule(schedules, target_date, default_schedule_id)
    courses = db.execute("SELECT * FROM courses WHERE schedule_id=%s ORDER BY name,id",
                         (schedule["id"],)).fetchall()
    catalog = {}
    for item in courses:
        normalized = "".join(str(item.get("name") or "").lower().split())
        if normalized and normalized not in catalog:
            catalog[normalized] = {"course_id": int(item["id"]), "name": str(item["name"])}
    return list(catalog.values())


def resolve_course_name(query: str, catalog: Sequence[Mapping]) -> dict:
    """Resolve a colloquial name locally; never guess when several names match."""
    def is_subsequence(short: str, long: str) -> bool:
        characters = iter(long)
        return all(character in characters for character in short)

    needle = "".join(str(query or "").lower().split())
    if not needle:
        return {"status": "not_found", "course": None, "candidates": []}
    exact, contained, subsequence = [], [], []
    for item in catalog:
        name = "".join(str(item.get("name") or "").lower().split())
        if name == needle:
            exact.append(dict(item))
        elif needle in name or name in needle:
            contained.append(dict(item))
        elif len(needle) >= 2 and is_subsequence(needle, name):
            subsequence.append(dict(item))
    matches = exact or contained or subsequence
    if len(matches) == 1:
        return {"status": "matched", "course": matches[0], "candidates": matches}
    return {"status": "ambiguous" if matches else "not_found", "course": None,
            "candidates": matches}
