"""课表路由：列表、更新、删除、调课版派生、示例课表。"""
import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..db import connect, row_dict
from ..schemas import ScheduleUpdate
from ..services.schedule_import import write_schedule

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
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM schedules WHERE user_id=%s ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
        if not rows:
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

        return [{**row_dict(row), "courses": courses_by_schedule.get(row["id"], [])} for row in rows]


@router.post("/{schedule_id}/adjusted", status_code=201)
def ensure_adjusted_schedule(schedule_id: int, user=Depends(get_current_user)):
    """为向下兼容保留；现在支持在原表上就地编辑，直接返回当前课表。"""
    with connect() as db:
        source = db.execute(
            "SELECT id FROM schedules WHERE id=%s AND user_id=%s",
            (schedule_id, user["id"]),
        ).fetchone()
        if not source:
            raise HTTPException(404, "课表不存在")
        return {"schedule_id": source["id"], "created": False, "course_map": {}}


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


@router.post("/demo", status_code=201)
def create_demo_schedule(user=Depends(get_current_user)):
    """为新用户与审核员提供一键体验示例课表，无需本地 Excel 文件即可体验完整课表。"""
    today = date.today()
    # 计算当前学期起始周一（让当前日期落在学期第 3 周，直观展示正在进行的课程）
    monday_offset = today.weekday()
    start_date = today - timedelta(days=monday_offset + 14)
    end_date = start_date + timedelta(weeks=16) - timedelta(days=1)
    year = today.year
    term_name = f"{year}年春季学期（示例）" if today.month in range(2, 8) else f"{year}年秋季学期（示例）"

    parsed = {
        "name": term_name,
        "term": term_name,
        "courses": [
            {"name": "高等数学(下)", "teacher": "张教授", "room": "公教楼 201", "weekday": 1,
             "start_section": 1, "end_section": 2, "weeks": list(range(1, 17)), "color": "#3b82f6"},
            {"name": "大学英语(四)", "teacher": "Smith", "room": "外语楼 302", "weekday": 1,
             "start_section": 3, "end_section": 4, "weeks": list(range(1, 17)), "color": "#10b981"},
            {"name": "计算机网络", "teacher": "李副教授", "room": "信息楼 405", "weekday": 2,
             "start_section": 1, "end_section": 2, "weeks": list(range(1, 17)), "color": "#8b5cf6"},
            {"name": "大学体育(羽毛球)", "teacher": "陈教练", "room": "体育馆 2号场", "weekday": 2,
             "start_section": 5, "end_section": 6, "weeks": list(range(1, 17)), "color": "#ec4899"},
            {"name": "数据结构与算法", "teacher": "王老师", "room": "机房 301", "weekday": 3,
             "start_section": 3, "end_section": 4, "weeks": list(range(1, 17)), "color": "#f59e0b"},
            {"name": "操作系统原理", "teacher": "周教授", "room": "信息楼 201", "weekday": 4,
             "start_section": 1, "end_section": 2, "weeks": list(range(1, 17)), "color": "#06b6d4"},
            {"name": "形势与政策", "teacher": "赵老师", "room": "大礼堂", "weekday": 5,
             "start_section": 3, "end_section": 4, "weeks": list(range(1, 9)), "color": "#f43f5e"},
        ],
    }
    with connect() as db:
        result = write_schedule(
            db,
            user_id=user["id"],
            parsed=parsed,
            overwrite=True,
            start_date=start_date,
            end_date=end_date,
        )
    return {
        "schedule_id": result["schedule_id"],
        "term_name": term_name,
        "imported": result["imported"],
        "replaced": result["replaced"],
    }
