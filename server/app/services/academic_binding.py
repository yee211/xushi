"""School associations and transactional sync shared by every client."""
import hashlib
import json
from datetime import date

from fastapi import HTTPException

from ..db import connect
from ..parser import normalize_courses
from . import academic, schedule_backups, user_cache
from .schedule_import import write_schedule


def lock_user(db, user_id):
    db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:academic-sync",))


def read_binding(user_id, use_cache=False):
    cached, cache_key = user_cache.read("academic-binding", user_id) if use_cache else (None, None)
    if isinstance(cached, dict):
        student = cached.get("student")
        if student:
            with academic._lock:
                academic._put(academic._students, student["id"], student, 5000)
        return cached
    with connect() as db:
        row = db.execute("""SELECT student,revision,updated_at,last_synced_at,last_synced_term
            FROM academic_bindings WHERE user_id=%s""", (user_id,)).fetchone()
    if not row:
        result = {"student": None}
        user_cache.store(cache_key, result)
        return result
    student = row["student"]
    with academic._lock:
        academic._put(academic._students, student["id"], student, 5000)
    result = dict(row)
    user_cache.store(cache_key, result)
    return result


def bind(user_id, student_id):
    student = academic.student_context(student_id)
    with connect() as db:
        lock_user(db, user_id)
        row = db.execute("""INSERT INTO academic_bindings(user_id,student) VALUES(%s,%s::jsonb)
            ON CONFLICT(user_id) DO UPDATE SET student=excluded.student,
                revision=academic_bindings.revision+1,updated_at=CURRENT_TIMESTAMP,
                last_synced_at=NULL,last_synced_term=NULL
            RETURNING student,revision,updated_at,last_synced_at,last_synced_term""",
            (user_id, json.dumps(student, ensure_ascii=False))).fetchone()
    user_cache.invalidate_user(user_id)
    return dict(row)


def unbind(user_id):
    with connect() as db:
        lock_user(db, user_id)
        db.execute("DELETE FROM academic_bindings WHERE user_id=%s", (user_id,))
    user_cache.invalidate_user(user_id)
    return {"student": None}


def snapshot_hash(snapshot):
    courses = normalize_courses(snapshot.get("courses") or [], exact=True)
    canonical = {"start_date": snapshot["start_date"], "end_date": snapshot["end_date"],
                 "courses": sorted(courses, key=lambda course: json.dumps(course, sort_keys=True))}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sync(user_id, term, refresh=False, expected_binding=None):
    bound = read_binding(user_id)
    student = bound["student"]
    if not student:
        raise HTTPException(409, "请先绑定学校身份")
    if expected_binding and (student["id"], bound["revision"], bound["updated_at"]) != expected_binding:
        raise HTTPException(409, "绑定已变更，请重新同步")
    snapshot = academic.get_schedule(student["id"], term, refresh)
    if snapshot.get("stale"):
        refresh_error = snapshot.get("refresh_error") or {}
        transient = {"upstream_failed": 502, "upstream_timeout": 504, "query_busy": 429, "rate_limit_unavailable": 503}
        if refresh_error.get("code") in transient:
            raise academic.AcademicError(refresh_error["code"], refresh_error.get("message") or "学校暂不可用，原课表已保留",
                                         transient[refresh_error["code"]])
    if snapshot.get("stale") or not snapshot.get("complete"):
        raise HTTPException(409, "学校连接暂不可用，未更新主课表，请恢复连接后重试")
    digest = snapshot_hash(snapshot)
    with connect() as db:
        lock_user(db, user_id)
        current = db.execute("SELECT student,revision,updated_at FROM academic_bindings WHERE user_id=%s FOR UPDATE",
                             (user_id,)).fetchone()
        if (not current or current["student"]["id"] != student["id"]
                or current["revision"] != bound["revision"]
                or current["updated_at"] != bound["updated_at"]):
            raise HTTPException(409, "绑定已变更，请重新同步")
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:schedule-import",))
        existing = db.execute("""SELECT id,name,term,start_date,end_date,academic_snapshot_hash FROM schedules
            WHERE user_id=%s AND variant_type IN ('original','draft')
            ORDER BY CASE WHEN academic_student_id=%s THEN 0 ELSE 1 END,id DESC LIMIT 1 FOR UPDATE""",
                               (user_id, student["id"])).fetchone()
        unchanged = False
        if existing and existing.get("academic_snapshot_hash") == digest:
            courses = db.execute("SELECT * FROM courses WHERE schedule_id=%s", (existing["id"],)).fetchall()
            current_snapshot = dict(snapshot, courses=[dict(course) for course in courses],
                                    start_date=str(existing["start_date"]), end_date=str(existing["end_date"]))
            unchanged = snapshot_hash(current_snapshot) == digest and existing["term"] == term
        if unchanged:
            result = {"schedule_id": existing["id"], "name": existing["name"], "term": term,
                      "imported": len(normalize_courses(snapshot.get("courses") or [], exact=True)), "replaced": False}
        else:
            schedule_backups.capture(db, user_id)
            parsed = dict(snapshot, term=term, name=f"{student['name']}的学校课表 · {term}")
            result = write_schedule(db, user_id=user_id, parsed=parsed, create_new=True,
                                    overwrite=True, target_schedule_id=existing["id"] if existing else None,
                                    preserve_adjusted=False, allow_empty=True, capture_backup=False, start_date=date.fromisoformat(snapshot["start_date"]),
                                    end_date=date.fromisoformat(snapshot["end_date"]), exact=True)
        db.execute("""UPDATE schedules SET academic_student_id=%s,academic_snapshot_hash=%s,
            academic_synced_at=CURRENT_TIMESTAMP WHERE id=%s AND user_id=%s""",
                   (student["id"], digest, result["schedule_id"], user_id))
        row = db.execute("""UPDATE academic_bindings SET last_synced_at=CURRENT_TIMESTAMP,last_synced_term=%s
            WHERE user_id=%s RETURNING last_synced_at""", (term, user_id)).fetchone()
        # The user explicitly chose one authoritative school schedule per account.
        # This runs only after a complete snapshot was validated and written successfully.
        if unchanged:
            other = db.execute("SELECT 1 FROM schedules WHERE user_id=%s AND id<>%s LIMIT 1",
                               (user_id, result["schedule_id"])).fetchone()
            if other:
                schedule_backups.capture(db, user_id)
        db.execute("DELETE FROM schedules WHERE user_id=%s AND id<>%s", (user_id, result["schedule_id"]))
    user_cache.invalidate_user(user_id)
    return dict(snapshot, **result, unchanged=unchanged, binding_revision=bound["revision"],
                last_synced_at=row["last_synced_at"], warnings=list(snapshot.get("warnings") or []),
                overwrite_policy="single_school_schedule")
