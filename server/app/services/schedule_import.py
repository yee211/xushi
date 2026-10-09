"""Validated, transactional schedule writes shared by every import source."""
import json
import re
from datetime import date

from fastapi import HTTPException

from ..parser import normalize_courses


def write_schedule(db, *, user_id: int, parsed: dict, overwrite: bool = False,
                   start_date: date | None = None, end_date: date | None = None, exact: bool = False,
                   create_new: bool = False, target_schedule_id: int | None = None,
                   preserve_adjusted: bool = False, allow_empty: bool = False, capture_backup: bool = True) -> dict:
    name = re.sub(r"\s+", " ", str(parsed.get("name") or parsed.get("term") or "教务系统课表")).strip()[:80] or "教务系统课表"
    term = re.sub(r"\s+", " ", str(parsed.get("term") or name)).strip()[:80] or name
    courses = normalize_courses(parsed.get("courses") or [], exact=exact)
    if not courses and not allow_empty:
        raise HTTPException(422, "没有可导入的课程")
    db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:schedule-import",))
    schedule = None if create_new else db.execute("""SELECT * FROM schedules
        WHERE user_id=%s AND (term=%s OR name=%s) AND variant_type IN ('original','draft')
        ORDER BY CASE WHEN term=%s THEN 0 ELSE 1 END,id DESC LIMIT 1 FOR UPDATE""",
        (user_id, term, name, term)).fetchone()
    if target_schedule_id is not None:
        schedule = db.execute("""SELECT * FROM schedules WHERE id=%s AND user_id=%s
            AND variant_type IN ('original','draft') FOR UPDATE""", (target_schedule_id, user_id)).fetchone()
        if not schedule:
            raise HTTPException(409, "学校课表已变更，请刷新后重新同步")
    replaced = schedule is not None
    if schedule and not overwrite:
        raise HTTPException(409, {"code": "schedule_exists", "message": f"已存在同名课表“{schedule['name']}”，是否覆盖？",
                                  "schedule_id": schedule["id"], "schedule_name": schedule["name"]})
    if schedule:
        if capture_backup:
            from .schedule_backups import capture
            capture(db, user_id)
        # 覆盖原始课表意味着建立一份新的基准数据。旧调课版是旧基准的完整副本，
        # 不能继续保留；先删除它，让其课程、单周调课和修改记录通过外键级联清理。
        if not preserve_adjusted:
            db.execute("""DELETE FROM schedules
                WHERE source_schedule_id=%s AND user_id=%s AND variant_type='adjusted'""",
                (schedule["id"], user_id))
        schedule = db.execute("""UPDATE schedules SET name=%s,term=%s,start_date=%s,end_date=%s,variant_type='original'
            WHERE id=%s AND user_id=%s RETURNING *""",
            (name, term, start_date, end_date, schedule["id"], user_id)).fetchone()
        db.execute("DELETE FROM courses WHERE schedule_id=%s", (schedule["id"],))
    else:
        schedule = db.execute("""INSERT INTO schedules(user_id,name,term,start_date,end_date,variant_type)
            VALUES(%s,%s,%s,%s,%s,'original') RETURNING *""",
            (user_id, name, term, start_date, end_date)).fetchone()
    rows = [(schedule["id"], c["name"], c["teacher"], c["room"], c["weekday"],
             c["start_section"], c["end_section"], json.dumps(c["weeks"]), c["color"])
            for c in courses]
    with db.cursor() as cursor:
        cursor.executemany("""INSERT INTO courses
            (schedule_id,name,teacher,room,weekday,start_section,end_section,weeks,color)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", rows)
    return {"imported": len(rows), "schedule_id": schedule["id"], "replaced": replaced,
            "term": schedule["term"], "name": schedule["name"]}
