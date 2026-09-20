"""课程路由：增删改 + 单周调课（含拖拽、幂等键、关联调课联动）。"""
import json

from fastapi import APIRouter, Depends, Header, HTTPException

from ..auth import get_current_user
from ..db import connect, row_dict
from ..schemas import CourseAdjustmentIn, CourseIn

router = APIRouter(prefix="/api/courses", tags=["courses"])

DAYS_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def reject_original_schedule(row) -> None:
    pass


def adjustment_conflicts(db, course_id: int, week: int, weekday: int, start_section: int, end_section: int) -> bool:
    owner = db.execute("SELECT schedule_id FROM courses WHERE id=%s", (course_id,)).fetchone()
    if not owner:
        return False
    rows = db.execute(
        """SELECT c.*, a.week AS adjusted_week, a.weekday AS adjusted_weekday,
                  a.start_section AS adjusted_start, a.end_section AS adjusted_end
           FROM courses c LEFT JOIN course_adjustments a
             ON a.course_id=c.id AND a.week=%s
           WHERE c.schedule_id=%s AND c.id<>%s""",
        (week, owner["schedule_id"], course_id),
    ).fetchall()
    for row in rows:
        if row["weeks"] and week not in row["weeks"]:
            continue
        other_day = row["adjusted_weekday"] if row["adjusted_week"] is not None else row["weekday"]
        other_start = row["adjusted_start"] if row["adjusted_week"] is not None else row["start_section"]
        other_end = row["adjusted_end"] if row["adjusted_week"] is not None else row["end_section"]
        if other_day == weekday and start_section <= other_end and end_section >= other_start:
            return True
    return False


def course_row_values(course: CourseIn):
    data = course.model_dump()
    return (
        data["schedule_id"],
        data["name"],
        data["teacher"],
        data["room"],
        data["weekday"],
        data["start_section"],
        data["end_section"],
        json.dumps(data["weeks"]),
        data["color"],
    )


@router.post("", status_code=201)
def add_course(course: CourseIn, user=Depends(get_current_user)):
    """添加单门课程。手动新增是对当前课表的补充，不是调课：原表仅对已有课程的
    修改、删除和单周调整保持只读，新增可直接写入。"""
    if course.end_section < course.start_section:
        raise HTTPException(400, "结束节次不能早于开始节次")
    with connect() as db:
        target_schedule = db.execute(
            "SELECT variant_type FROM schedules WHERE id=%s AND user_id=%s",
            (course.schedule_id, user["id"]),
        ).fetchone()
        if not target_schedule:
            raise HTTPException(404, "课表不存在")
        row = db.execute(
            """INSERT INTO courses
            (schedule_id,name,teacher,room,weekday,start_section,end_section,weeks,color)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *""",
            course_row_values(course),
        ).fetchone()
        return row_dict(row)


@router.put("/{course_id}")
def update_course(
    course_id: int,
    course: CourseIn,
    source: str = "manual",
    link_adjustments: bool = False,
    user=Depends(get_current_user),
):
    """更新指定课程信息；link_adjustments=true 时联动平移所有单周调课。"""
    if course.end_section < course.start_section:
        raise HTTPException(400, "结束节次不能早于开始节次")
    with connect() as db:
        target_schedule = db.execute(
            "SELECT variant_type FROM schedules WHERE id=%s AND user_id=%s",
            (course.schedule_id, user["id"]),
        ).fetchone()
        if not target_schedule:
            raise HTTPException(404, "课表不存在")
        reject_original_schedule(target_schedule)
        old_course = db.execute(
            """SELECT c.*,s.variant_type FROM courses c JOIN schedules s ON s.id=c.schedule_id
               WHERE c.id=%s AND s.user_id=%s""",
            (course_id, user["id"]),
        ).fetchone()
        if not old_course:
            raise HTTPException(404, "课程不存在")
        reject_original_schedule(old_course)

        weekday_delta = course.weekday - old_course["weekday"]
        start_section_delta = course.start_section - old_course["start_section"]
        end_section_delta = course.end_section - old_course["end_section"]
        linked_adjustments = []
        if link_adjustments and (weekday_delta or start_section_delta or end_section_delta):
            linked_adjustments = db.execute(
                "SELECT * FROM course_adjustments WHERE course_id=%s ORDER BY week FOR UPDATE",
                (course_id,),
            ).fetchall()
            if any(
                not 1 <= item["weekday"] + weekday_delta <= 7
                or not 1 <= item["start_section"] + start_section_delta <= 12
                or not 1 <= item["end_section"] + end_section_delta <= 12
                or item["end_section"] + end_section_delta < item["start_section"] + start_section_delta
                for item in linked_adjustments
            ):
                raise HTTPException(409, "基础时间的改动会使关联调课超出星期或节次范围，请先撤销相关调课")
            for item in linked_adjustments:
                target_weekday = item["weekday"] + weekday_delta
                target_start = item["start_section"] + start_section_delta
                target_end = item["end_section"] + end_section_delta
                if adjustment_conflicts(db, course_id, item["week"], target_weekday, target_start, target_end):
                    raise HTTPException(409, f"第 {item['week']} 周关联调课平移后与现有课程冲突，请先调整或撤销相关调课")

        row = db.execute(
            """UPDATE courses SET schedule_id=%s,name=%s,teacher=%s,room=%s,
            weekday=%s,start_section=%s,end_section=%s,weeks=%s::jsonb,color=%s
            WHERE id=%s AND EXISTS (
                SELECT 1 FROM schedules s WHERE s.id=courses.schedule_id AND s.user_id=%s
            ) RETURNING *""",
            (*course_row_values(course), course_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "课程不存在")

        if linked_adjustments:
            db.execute(
                """UPDATE course_adjustments
                SET weekday=weekday+%s,start_section=start_section+%s,end_section=end_section+%s
                WHERE course_id=%s""",
                (weekday_delta, start_section_delta, end_section_delta, course_id),
            )

        diffs = []
        if (old_course["weekday"], old_course["start_section"], old_course["end_section"]) != (
            course.weekday, course.start_section, course.end_section,
        ):
            diffs.append({
                "field": "time",
                "label": "上课时间",
                "old": f"{DAYS_NAMES[old_course['weekday']-1]} 第{old_course['start_section']}-{old_course['end_section']}节",
                "new": f"{DAYS_NAMES[course.weekday-1]} 第{course.start_section}-{course.end_section}节",
                "old_weekday": old_course["weekday"],
                "old_start_section": old_course["start_section"],
                "old_end_section": old_course["end_section"],
                "new_weekday": course.weekday,
                "new_start_section": course.start_section,
                "new_end_section": course.end_section,
            })
        for field, label in (("room", "教室地点"), ("teacher", "授课教师"), ("name", "课程名称")):
            if (old_course[field] or "") != (getattr(course, field) or ""):
                diffs.append({
                    "field": field,
                    "label": label,
                    "old": old_course[field] or "未设置",
                    "new": getattr(course, field) or "未设置",
                })

        if diffs:
            is_drag = source == "drag"
            db.execute(
                """INSERT INTO course_change_logs(schedule_id, course_id, action_type, title, description, details)
                   VALUES(%s, %s, %s, %s, %s, %s::jsonb)""",
                (
                    course.schedule_id,
                    course_id,
                    "drag_move" if is_drag else "manual_edit",
                    "位置移动（修改时间）" if is_drag else "主动编辑课程",
                    f"拖拽将《{course.name}》移动至 {DAYS_NAMES[course.weekday-1]} 第{course.start_section}-{course.end_section}节（所有周次）"
                    if is_drag else f"修改了《{course.name}》的" + "、".join(d["label"] for d in diffs),
                    json.dumps(diffs, ensure_ascii=False),
                ),
            )

        return row_dict(row)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: int, user=Depends(get_current_user)):
    """删除指定课程。"""
    with connect() as db:
        deleted = db.execute(
            """DELETE FROM courses WHERE id=%s AND EXISTS (
                SELECT 1 FROM schedules s WHERE s.id=courses.schedule_id AND s.user_id=%s
            ) RETURNING id""",
            (course_id, user["id"]),
        ).fetchone()
        if not deleted:
            raise HTTPException(404, "课程不存在")


@router.put("/{course_id}/adjustments/{week}")
def upsert_adjustment(
    course_id: int,
    week: int,
    payload: CourseAdjustmentIn,
    source: str = "drag",
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user=Depends(get_current_user),
):
    """新增或更新某门课程在指定周的临时调课安排（支持幂等重试）。"""
    if idempotency_key and len(idempotency_key) > 80:
        raise HTTPException(400, "幂等请求编号过长")
    if week != payload.week or payload.end_section < payload.start_section:
        raise HTTPException(400, "调课周次或节次不正确")
    with connect() as db:
        course = db.execute(
            """SELECT c.*,s.variant_type FROM courses c JOIN schedules s ON s.id=c.schedule_id
               WHERE c.id=%s AND s.user_id=%s FOR UPDATE OF c""",
            (course_id, user["id"]),
        ).fetchone()
        if not course:
            raise HTTPException(404, "课程不存在")
        reject_original_schedule(course)
        if idempotency_key:
            duplicate = db.execute(
                "SELECT 1 FROM course_change_logs WHERE schedule_id=%s AND request_id=%s",
                (course["schedule_id"], idempotency_key),
            ).fetchone()
            if duplicate:
                current = db.execute(
                    "SELECT * FROM course_adjustments WHERE course_id=%s AND week=%s",
                    (course_id, week),
                ).fetchone()
                return {**(row_dict(current) if current else {}), "duplicate": True}
        if course["weeks"] and week not in course["weeks"]:
            raise HTTPException(400, "该课程在指定周次没有排课")
        previous = db.execute(
            "SELECT * FROM course_adjustments WHERE course_id=%s AND week=%s",
            (course_id, week),
        ).fetchone()
        old_weekday = previous["weekday"] if previous else course["weekday"]
        old_start = previous["start_section"] if previous else course["start_section"]
        old_end = previous["end_section"] if previous else course["end_section"]
        old_room = (previous["room"] if previous else course["room"]) or ""
        new_values = (payload.weekday, payload.start_section, payload.end_section, payload.room.strip())
        if new_values == (old_weekday, old_start, old_end, old_room):
            return {**(row_dict(previous) if previous else {}), "unchanged": True}
        if adjustment_conflicts(db, course_id, week, payload.weekday, payload.start_section, payload.end_section):
            raise HTTPException(409, "目标时段与现有课程冲突")
        row = db.execute(
            """INSERT INTO course_adjustments
               (course_id,week,weekday,start_section,end_section,room)
               VALUES(%s,%s,%s,%s,%s,%s)
               ON CONFLICT(course_id,week) DO UPDATE SET
                 weekday=EXCLUDED.weekday,start_section=EXCLUDED.start_section,
                 end_section=EXCLUDED.end_section,room=EXCLUDED.room
               RETURNING *""",
            (course_id, week, payload.weekday, payload.start_section, payload.end_section, payload.room.strip()),
        ).fetchone()

        old_time = f"{DAYS_NAMES[old_weekday-1]} 第{old_start}-{old_end}节"
        new_time = f"{DAYS_NAMES[payload.weekday-1]} 第{payload.start_section}-{payload.end_section}节"
        details = [{
            "field": "time",
            "label": "上课时间",
            "old": old_time,
            "new": new_time,
            "course_id": course_id,
            "course_name": course["name"],
            "week": week,
            "old_weekday": old_weekday,
            "old_start_section": old_start,
            "old_end_section": old_end,
            "old_room": old_room,
            "new_weekday": payload.weekday,
            "new_start_section": payload.start_section,
            "new_end_section": payload.end_section,
            "new_room": payload.room.strip(),
            "can_revoke": True,
        }]
        if payload.room.strip() != old_room:
            details.append({
                "field": "room",
                "label": "教室地点",
                "old": old_room or "未设置",
                "new": payload.room or "未设置",
            })
        description = f"第 {week} 周将《{course['name']}》从 {old_time} 调整至 {new_time}"
        if payload.room.strip() != old_room:
            description += f"（教室：{payload.room}）"

        db.execute(
            """INSERT INTO course_change_logs(schedule_id, course_id, action_type, title, description, details, request_id)
               VALUES(%s, %s, %s, %s, %s, %s::jsonb, %s)""",
            (
                course["schedule_id"],
                course_id,
                "drag_move" if source == "drag" else "manual_edit",
                "位置移动（修改时间）" if source == "drag" else "主动编辑（单周调课）",
                description,
                json.dumps(details, ensure_ascii=False),
                idempotency_key,
            ),
        )

        return row_dict(row)


@router.delete("/{course_id}/adjustments/{week}", status_code=204)
def delete_adjustment(course_id: int, week: int, user=Depends(get_current_user)):
    """撤销指定周的调课，恢复课程原安排。"""
    with connect() as db:
        deleted = db.execute(
            """DELETE FROM course_adjustments a USING courses c, schedules s
               WHERE a.course_id=%s AND a.week=%s AND c.id=a.course_id
                 AND s.id=c.schedule_id AND s.user_id=%s RETURNING a.id""",
            (course_id, week, user["id"]),
        ).fetchone()
        if not deleted:
            raise HTTPException(404, "调课记录不存在")
