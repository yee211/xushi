"""Saved read-only school timetables, isolated from personal schedule sync."""
import json
import re
from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..db import connect, db_ctx
from ..rate_limit import SlidingWindowLimiter
from . import academic, academic_rate_limit
from .schedule_query import (
    APP_TIMEZONE,
    PERIOD_SECTIONS,
    SECTION_BY_NUMBER,
    ScheduleQueryError,
    materialize_courses,
    query_courses_by_date,
    teaching_week,
)

query_limiter = SlidingWindowLimiter(10, 60, prefix="xushi:ratelimit:other-schedules")
MAX_SAVED_PEOPLE = 50


def check_query_limit(user_id):
    allowed, _ = query_limiter.hit(str(user_id))
    if not allowed:
        raise academic.AcademicError("too_many_queries", "查询过于频繁，请稍后重试", 429)


def list_saved(user_id):
    with connect() as db:
        rows = db.execute("SELECT student_id,term,remark,snapshot,updated_at FROM academic_others WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
    return {"people": [dict(row) for row in rows]}


def query(student_id, term, refresh=False, user_id=None):
    if user_id is not None:
        check_query_limit(user_id)
    # Multi-request semester queries need more queue time than directory lookups.
    # Keep the shared one-request-per-second limit and the client's total deadline.
    with academic_rate_limit.query_wait(15):
        snapshot = academic.get_schedule(student_id, term, refresh)
    if snapshot.get("stale"):
        error = snapshot.get("refresh_error") or {}
        code = error.get("code") or "upstream_failed"
        status = {"upstream_timeout": 504, "query_busy": 429, "connection_expired": 409,
                  "rate_limit_unavailable": 503}.get(code, 502)
        raise academic.AcademicError(code, (error.get("message") or "学校课表暂不可用") + "；已保存的课表保持不变", status)
    if not snapshot.get("complete"):
        raise academic.AcademicError("snapshot_incomplete", "学校未返回完整课表，已保存的课表保持不变，请稍后重试", 409)
    return snapshot


def _upsert_row(db, user_id, student_id, term, remark, snapshot):
    db.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
    counts = db.execute("""SELECT COUNT(*) AS total,
        COUNT(*) FILTER (WHERE student_id=%s) AS present FROM academic_others WHERE user_id=%s""",
        (student_id, user_id)).fetchone()
    if counts["total"] >= MAX_SAVED_PEOPLE and not counts["present"]:
        raise academic.AcademicError("saved_people_limit", "最多保存50位同学的课表，请先移除不需要的收藏", 409)
    row = db.execute("""INSERT INTO academic_others(user_id,student_id,term,remark,snapshot)
        VALUES(%s,%s,%s,COALESCE(%s,''),%s::jsonb) ON CONFLICT(user_id,student_id) DO UPDATE
        SET term=excluded.term,remark=CASE WHEN %s::text IS NULL THEN academic_others.remark ELSE excluded.remark END,
        snapshot=excluded.snapshot,updated_at=CURRENT_TIMESTAMP
        RETURNING student_id,term,remark,snapshot,updated_at""",
        (user_id, student_id, term, remark.strip() if remark is not None else None,
         json.dumps(snapshot, ensure_ascii=False), remark)).fetchone()
    return dict(row)


def save(user_id, student_id, term, remark=None):
    snapshot = query(student_id, term, user_id=user_id)
    with connect() as db:
        return _upsert_row(db, user_id, student_id, term, remark, snapshot)


def remove(user_id, student_id):
    with connect() as db:
        db.execute("DELETE FROM academic_others WHERE user_id=%s AND student_id=%s", (user_id, student_id))


def refresh_saved(user_id, student_id):
    with connect() as db:
        old = db.execute("SELECT * FROM academic_others WHERE user_id=%s AND student_id=%s", (user_id, student_id)).fetchone()
    if not old:
        raise academic.AcademicError("saved_person_changed", "此人的课表已被移除，请刷新列表", 409)
    snapshot = query(student_id, old["term"], True, user_id)
    with connect() as db:
        row = db.execute("""UPDATE academic_others SET snapshot=%s::jsonb, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=%s AND student_id=%s AND term=%s AND updated_at=%s
            RETURNING student_id,term,remark,snapshot,updated_at""",
            (json.dumps(snapshot, ensure_ascii=False), user_id, student_id, old["term"], old["updated_at"])).fetchone()
    if not row:
        raise academic.AcademicError("saved_person_changed", "此人的课表已被修改或移除，未覆盖新数据，请刷新列表", 409)
    return dict(row)


def _person_meta(row: dict) -> dict:
    raw_snapshot = row.get("snapshot") or {}
    snapshot = json.loads(raw_snapshot) if isinstance(raw_snapshot, str) else dict(raw_snapshot)
    student = dict(snapshot.get("student") or {})
    name = str(student.get("name") or "").strip()
    remark = str(row.get("remark") or "").strip()
    display_name = f"{remark}（{name}）" if remark and name and remark != name else (remark or name or str(row.get("student_id") or ""))
    return {
        "student_id": str(row.get("student_id") or ""),
        "name": name,
        "remark": remark,
        "display_name": display_name,
        "class_name": str(student.get("class_name") or ""),
        "major_name": str(student.get("major_name") or ""),
        "grade": str(student.get("grade") or ""),
        "term": str(row.get("term") or snapshot.get("term") or ""),
        "start_date": snapshot.get("start_date"),
        "end_date": snapshot.get("end_date"),
        "updated_at": str(row.get("updated_at") or ""),
        "fetched_at": snapshot.get("fetched_at"),
    }


def _load_saved_rows(db, user_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT student_id,term,remark,snapshot,updated_at FROM academic_others WHERE user_id=%s ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_saved_summary(db, user_id: int) -> dict:
    rows = _load_saved_rows(db, user_id)
    return {"people": [_person_meta(row) for row in rows]}


def resolve_saved_person(rows: Sequence[dict], query_text: str) -> dict:
    needle = re.sub(r"[\s()（）·,，、:：\"'“”‘’]+", "", str(query_text or "").lower())
    if not rows:
        raise ScheduleQueryError(
            "NO_OTHER_SCHEDULES",
            "你还没有保存任何他人课表，可以先告诉我“帮我加一下某某的课表”或去小程序“他人课表”中添加。",
        )
    if not needle:
        if len(rows) == 1:
            return rows[0]
        candidates = [_person_meta(r) for r in rows]
        names = "、".join(c["display_name"] for c in candidates)
        raise ScheduleQueryError("AMBIGUOUS_PERSON", f"你保存了多位同学的课表（{names}），请说明要查哪一位？", candidates)
    exact, contained = [], []
    for row in rows:
        meta = _person_meta(row)
        sid = meta["student_id"].lower()
        remark = re.sub(r"[\s()（）·,，、:：\"'“”‘’]+", "", meta["remark"].lower())
        name = re.sub(r"[\s()（）·,，、:：\"'“”‘’]+", "", meta["name"].lower())
        cls = re.sub(r"[\s()（）·,，、:：\"'“”‘’]+", "", meta["class_name"].lower())
        display = re.sub(r"[\s()（）·,，、:：\"'“”‘’]+", "", meta["display_name"].lower())
        if needle in {sid, remark, name, display} and needle:
            exact.append(row)
        elif any(needle in field or (field and field in needle) for field in (remark, name, cls, display)):
            contained.append(row)
    matches = exact or contained
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = [_person_meta(r) for r in matches]
        names = "、".join(c["display_name"] for c in candidates)
        raise ScheduleQueryError("AMBIGUOUS_PERSON", f"“{query_text}”匹配到多位已保存的同学：{names}。请指明是哪一位？", candidates)
    candidates = [_person_meta(r) for r in rows]
    names = "、".join(c["display_name"] for c in candidates)
    raise ScheduleQueryError(
        "PERSON_NOT_FOUND",
        f"在已保存的他人课表中没有找到“{query_text}”（当前已保存：{names}）。如果需要添加，可以说“帮我添加{query_text}的课表”。",
        candidates,
    )


def _materialize_other_row(row: dict, target_date: date, period: str = "all") -> dict:
    raw_snapshot = row.get("snapshot") or {}
    snapshot = json.loads(raw_snapshot) if isinstance(raw_snapshot, str) else dict(raw_snapshot)
    meta = _person_meta(row)
    week = teaching_week(snapshot, target_date)
    if week is None:
        raise ScheduleQueryError("OUTSIDE_TERM", f"目标日期不在 {meta['display_name']} 课表的学期范围内")
    raw_courses = snapshot.get("courses") or []
    indexed_courses = [dict(course, id=course.get("id", idx)) for idx, course in enumerate(raw_courses, 1)]
    courses = materialize_courses(indexed_courses, [], week, target_date.isoweekday(), period)
    return {
        "person": meta,
        "date": target_date.isoformat(),
        "weekday": target_date.isoweekday(),
        "week": week,
        "period": period,
        "term": meta["term"],
        "timezone": APP_TIMEZONE,
        "courses": courses,
    }


def query_other_courses_by_date(db, user_id: int, person_query: str, target_date: date, period: str = "all") -> dict:
    rows = _load_saved_rows(db, user_id)
    matched = resolve_saved_person(rows, person_query)
    return _materialize_other_row(matched, target_date, period)


def _contiguous_slots(sections: Sequence[int]) -> list[dict]:
    sorted_nums = sorted({int(s) for s in sections if int(s) in SECTION_BY_NUMBER})
    if not sorted_nums:
        return []
    ranges = []
    start = prev = sorted_nums[0]
    for num in sorted_nums[1:]:
        if num == prev + 1:
            prev = num
        else:
            ranges.append((start, prev))
            start = prev = num
    ranges.append((start, prev))
    return [
        {
            "start_section": s,
            "end_section": e,
            "start_time": SECTION_BY_NUMBER[s].start.strftime("%H:%M"),
            "end_time": SECTION_BY_NUMBER[e].end.strftime("%H:%M"),
        }
        for s, e in ranges
    ]


def check_group_availability(
    db,
    user_id: int,
    target_date: date,
    period: str = "all",
    people_queries: Sequence[str] | None = None,
    include_me: bool = True,
    default_schedule_id: int | None = None,
) -> dict:
    if period not in PERIOD_SECTIONS:
        raise ScheduleQueryError("INVALID_PERIOD", "无效的时间段")
    p_start, p_end = PERIOD_SECTIONS[period]
    all_sections = set(range(p_start, p_end + 1))
    rows = _load_saved_rows(db, user_id)
    selected_rows = []
    if people_queries:
        seen_ids = set()
        for q in people_queries:
            if not str(q or "").strip():
                continue
            matched = resolve_saved_person(rows, str(q))
            sid = matched["student_id"]
            if sid not in seen_ids:
                seen_ids.add(sid)
                selected_rows.append(matched)
    else:
        selected_rows = list(rows)
    if not selected_rows:
        raise ScheduleQueryError("NO_OTHER_SCHEDULES", "你还没有保存可比对的他人课表，请先添加同学的课表。")

    participants = []
    if include_me:
        try:
            my_day = query_courses_by_date(db, user_id, target_date, period, default_schedule_id)
            my_courses = my_day.get("courses") or []
            occupied = {
                sec
                for c in my_courses
                for sec in range(max(p_start, int(c["start_section"])), min(p_end, int(c["end_section"])) + 1)
            }
            free_secs = sorted(all_sections - occupied)
            participants.append({
                "role": "me",
                "display_name": "我",
                "name": "我",
                "remark": "",
                "completely_free": len(occupied) == 0,
                "course_count": len(my_courses),
                "courses": my_courses,
                "free_slots": _contiguous_slots(free_secs),
                "_free_set": set(free_secs),
            })
        except ScheduleQueryError as error:
            raise ScheduleQueryError(
                error.code, f"无法确认你的课表，不能计算共同空闲：{error.message}", error.candidates,
            ) from error

    for row in selected_rows:
        meta = _person_meta(row)
        try:
            day_data = _materialize_other_row(row, target_date, period)
            courses = day_data["courses"]
        except ScheduleQueryError as error:
            raise ScheduleQueryError(
                error.code, f"无法确认 {meta['display_name']} 的课表，不能计算共同空闲：{error.message}",
                error.candidates,
            ) from error
        occupied = {
            sec
            for c in courses
            for sec in range(max(p_start, int(c["start_section"])), min(p_end, int(c["end_section"])) + 1)
        }
        free_secs = sorted(all_sections - occupied)
        participants.append({
            "role": "other",
            "term": meta["term"],
            "updated_at": meta["updated_at"],
            "fetched_at": meta["fetched_at"],
            "student_id": meta["student_id"],
            "display_name": meta["display_name"],
            "name": meta["name"],
            "remark": meta["remark"],
            "completely_free": len(occupied) == 0,
            "course_count": len(courses),
            "courses": courses,
            "free_slots": _contiguous_slots(free_secs),
            "_free_set": set(free_secs),
        })

    if not participants:
        raise ScheduleQueryError(
            "NO_PARTICIPANTS",
            "没有可比对的课表数据（请先导入自己的课表或在“他人课表”中保存同学的课表）。",
        )

    common_free_set = set(all_sections)
    for p in participants:
        common_free_set &= p.pop("_free_set")

    return {
        "date": target_date.isoformat(),
        "weekday": target_date.isoweekday(),
        "period": period,
        "period_time": {
            "start_time": SECTION_BY_NUMBER[p_start].start.strftime("%H:%M"),
            "end_time": SECTION_BY_NUMBER[p_end].end.strftime("%H:%M"),
        },
        "participants": participants,
        "completely_free_people": [p["display_name"] for p in participants if p["completely_free"]],
        "busy_people": [p["display_name"] for p in participants if not p["completely_free"]],
        "common_free_slots": _contiguous_slots(sorted(common_free_set)),
    }


def _default_term_for_user(db, user_id: int, student: dict) -> str:
    preferred = str(student.get("default_term") or "")
    if re.fullmatch(r"\d{4}-\d{4}-[12]", preferred):
        return preferred
    today = datetime.now(ZoneInfo(APP_TIMEZONE)).date()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{start_year + 1}-{'1' if today.month >= 8 or today.month == 1 else '2'}"


def search_and_save_other(db_or_factory, user_id: int, keyword: str, remark: str | None = None, term: str = "", student_id: str = "") -> dict:
    check_query_limit(user_id)
    sid = str(student_id or "").strip()
    kw = str(keyword or "").strip()
    chosen_student = None
    if sid:
        try:
            chosen_student = academic.student_context(sid)
        except academic.AcademicError:
            chosen_student = None
    if chosen_student is None:
        if not kw:
            return {"ok": False, "error": "ADD_NEEDS_INPUT", "status": "needs_input", "message": "请提供要添加同学的姓名、班级或关键词。"}
        search_res = academic.search_keyword(kw)
        students = search_res.get("students") or []
        if not students:
            return {"ok": False, "error": "STUDENT_NOT_FOUND", "status": "not_found", "keyword": kw, "message": f"没有在学校名录中找到与“{kw}”匹配的学生。"}
        if len(students) > 1:
            # Check if keyword exactly matches a single student_number_display or id
            exact_id = [s for s in students if s.get("id") == kw or s.get("student_number_display") == kw]
            if len(exact_id) == 1:
                chosen_student = exact_id[0]
            else:
                candidates = [
                    {
                        "student_id": s.get("id"),
                        "name": s.get("name"),
                        "grade": s.get("grade"),
                        "class_name": s.get("class_name"),
                        "major_name": s.get("major_name"),
                        "student_number_display": s.get("student_number_display"),
                    }
                    for s in students[:8]
                ]
                summary = "；".join(
                    f"{i}. {c['name']}（{c['grade']}级 {c['class_name']} {c['student_number_display']}）"
                    for i, c in enumerate(candidates, 1)
                )
                return {
                    "ok": False,
                    "error": "AMBIGUOUS_PERSON",
                    "status": "ambiguous",
                    "keyword": kw,
                    "total_matches": len(students),
                    "candidates": candidates,
                    "message": f"找到 {len(students)} 位匹配“{kw}”的同学：{summary}。请告诉我具体的班级或学号来确认添加哪一位？",
                }
        else:
            chosen_student = students[0]

    target_term = str(term or "").strip()
    if not re.fullmatch(r"\d{4}-\d{4}-[12]", target_term):
        target_term = _default_term_for_user(None, user_id, chosen_student)

    snapshot = query(chosen_student["id"], target_term)
    with db_ctx(db_or_factory) as db:
        saved_row = _upsert_row(db, user_id, chosen_student["id"], target_term, remark, snapshot)
    meta = _person_meta(saved_row)
    return {
        "ok": True,
        "status": "saved",
        "person": meta,
        "course_count": len(snapshot.get("courses") or []),
        "message": f"已添加 {meta['display_name']}（{meta['class_name']}，{meta['term']} 学期）的课表。",
    }

