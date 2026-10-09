"""课表路由：列表、更新和删除。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..db import connect, row_dict
from ..schemas import ScheduleUpdate
from ..services import user_cache

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def parse_schedule_date(value: str | None, label: str):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(400, f"{label}格式应为 YYYY-MM-DD") from error


def _attach_courses(db, schedule_row) -> dict:
    """把课表的课程与单周调课一次性装配进响应（批量查询消除 N+1）。"""
    courses = db.execute(
        "SELECT * FROM courses WHERE schedule_id=%s ORDER BY weekday,start_section",
        (schedule_row["id"],),
    ).fetchall()
    adjustments_by_course: dict[int, list[dict]] = {course["id"]: [] for course in courses}
    if courses:
        for adjustment in db.execute(
            "SELECT * FROM course_adjustments WHERE course_id = ANY(%s) ORDER BY week",
            ([course["id"] for course in courses],),
        ).fetchall():
            adjustments_by_course[adjustment["course_id"]].append(row_dict(adjustment))
    result = row_dict(schedule_row)
    result["courses"] = []
    for course in courses:
        item = row_dict(course)
        item["adjustments"] = adjustments_by_course.get(course["id"], [])
        result["courses"].append(item)
    return result


@router.get("")
def list_schedules(user=Depends(get_current_user)):
    """获取当前用户的所有课表及其课程列表。"""
    cached, cache_key = user_cache.read("schedules", user["id"])
    if isinstance(cached, list):
        return cached
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM schedules WHERE user_id=%s ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
        if not rows:
            user_cache.store(cache_key, [])
            return []

        schedule_ids = [row["id"] for row in rows]
        courses_rows = db.execute(
            "SELECT * FROM courses WHERE schedule_id = ANY(%s) ORDER BY weekday, start_section",
            (schedule_ids,),
        ).fetchall()
        course_ids = [course["id"] for course in courses_rows]
        adjustments_by_course: dict[int, list[dict]] = {cid: [] for cid in course_ids}
        if course_ids:
            adjustment_rows = db.execute(
                "SELECT * FROM course_adjustments WHERE course_id = ANY(%s) ORDER BY week",
                (course_ids,),
            ).fetchall()
            for adjustment in adjustment_rows:
                adjustments_by_course[adjustment["course_id"]].append(row_dict(adjustment))
        courses_by_schedule: dict[int, list[dict]] = {sid: [] for sid in schedule_ids}
        for course in courses_rows:
            item = row_dict(course)
            item["adjustments"] = adjustments_by_course.get(course["id"], [])
            courses_by_schedule[course["schedule_id"]].append(item)

        result = [{**row_dict(row), "courses": courses_by_schedule.get(row["id"], [])} for row in rows]
    user_cache.store(cache_key, result)
    return result


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, payload: ScheduleUpdate, user=Depends(get_current_user)):
    """更新课表的基础信息（名称、学期、开学日期、结束日期）。"""
    with connect() as db:
        schedule = db.execute(
            "SELECT * FROM schedules WHERE id=%s AND user_id=%s",
            (schedule_id, user["id"]),
        ).fetchone()
        if not schedule:
            raise HTTPException(404, "课表不存在")

        new_name = payload.name.strip() if payload.name is not None else schedule["name"]
        new_term = payload.term.strip() if payload.term is not None else schedule["term"]
        new_start = parse_schedule_date(payload.start_date, "开学日期") if payload.start_date is not None else schedule["start_date"]
        new_end = parse_schedule_date(payload.end_date, "结束日期") if payload.end_date is not None else schedule["end_date"]

        if new_start and new_end and new_end < new_start:
            raise HTTPException(400, "结束日期不能早于开学日期")

        updated = db.execute(
            """UPDATE schedules SET name=%s, term=%s, start_date=%s, end_date=%s
               WHERE id=%s AND user_id=%s RETURNING *""",
            (new_name, new_term, new_start, new_end, schedule_id, user["id"]),
        ).fetchone()
        return _attach_courses(db, updated)


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, user=Depends(get_current_user)):
    """删除指定的课表，级联删除下属所有课程；有调课版时要求先删调课版。"""
    with connect() as db:
        source = db.execute(
            "SELECT variant_type FROM schedules WHERE id=%s AND user_id=%s",
            (schedule_id, user["id"]),
        ).fetchone()
        if source and source["variant_type"] == "original" and db.execute(
            "SELECT 1 FROM schedules WHERE source_schedule_id=%s", (schedule_id,)
        ).fetchone():
            raise HTTPException(409, "请先删除该学期的调课版，再删除原始课表")
        if not db.execute(
            "DELETE FROM schedules WHERE id=%s AND user_id=%s RETURNING id",
            (schedule_id, user["id"]),
        ).fetchone():
            raise HTTPException(404, "课表不存在")
