"""Transactional recovery points before school sync overwrites user data."""
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from ..db import connect
from . import user_cache

SCHEMA = """CREATE TABLE IF NOT EXISTS schedule_backups (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
INDEX = "CREATE INDEX IF NOT EXISTS idx_schedule_backups_user ON schedule_backups(user_id,id DESC)"
TABLES = ("schedules", "courses", "course_adjustments", "course_change_logs")


def capture(db, user_id):
    # Share the import lock so two school sync/recovery writes cannot interleave.
    db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:schedule-import",))
    schedules = db.execute("SELECT * FROM schedules WHERE user_id=%s ORDER BY id FOR UPDATE", (user_id,)).fetchall()
    if not schedules:
        return None
    ids = [row["id"] for row in schedules]
    courses = db.execute("SELECT * FROM courses WHERE schedule_id=ANY(%s) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    course_ids = [row["id"] for row in courses]
    adjustments = db.execute("SELECT * FROM course_adjustments WHERE course_id=ANY(%s) ORDER BY id FOR UPDATE", (course_ids,)).fetchall()
    logs = db.execute("SELECT * FROM course_change_logs WHERE schedule_id=ANY(%s) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    payload = dict(zip(TABLES, (schedules, courses, adjustments, logs), strict=True))
    row = db.execute("INSERT INTO schedule_backups(user_id,payload) VALUES(%s,%s::jsonb) RETURNING id",
                     (user_id, json.dumps(jsonable_encoder(payload), ensure_ascii=False))).fetchone()
    # Bounded storage, including users whose school timetable never changes again.
    db.execute("""DELETE FROM schedule_backups WHERE user_id=%s AND id NOT IN
        (SELECT id FROM schedule_backups WHERE user_id=%s ORDER BY id DESC LIMIT 5)""", (user_id, user_id))
    return row["id"]


def list_backups(user_id):
    with connect() as db:
        rows = db.execute("""SELECT id,created_at,jsonb_array_length(payload->'schedules') AS schedule_count
            FROM schedule_backups WHERE user_id=%s ORDER BY id DESC LIMIT 5""", (user_id,)).fetchall()
    return {"backups": rows}


def restore(user_id, backup_id):
    # Lock ordering matches school sync. Reject recovery while a job is active.
    from .academic_binding import lock_user

    with connect() as db:
        lock_user(db, user_id)
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:schedule-import",))
        if db.execute("SELECT 1 FROM academic_sync_jobs WHERE user_id=%s AND state IN ('queued','running')", (user_id,)).fetchone():
            raise HTTPException(409, "请等待学校同步任务结束后再恢复")
        row = db.execute("SELECT payload FROM schedule_backups WHERE id=%s AND user_id=%s FOR UPDATE", (backup_id, user_id)).fetchone()
        if not row:
            raise HTTPException(404, "恢复记录不存在")
        payload = row["payload"]
        capture(db, user_id)
        db.execute("DELETE FROM schedules WHERE user_id=%s", (user_id,))
        # Insert all rows of each table in one statement, preserving IDs and FK links.
        # Table names come exclusively from this fixed internal allowlist.
        for table in TABLES:
            db.execute(f"INSERT INTO {table} SELECT * FROM jsonb_populate_recordset(NULL::{table},%s::jsonb)",
                       (json.dumps(payload[table], ensure_ascii=False),))
        # Invalidate any legacy synchronous fetch that started before recovery.
        db.execute("""UPDATE academic_bindings SET revision=revision+1,updated_at=CURRENT_TIMESTAMP,
            last_synced_at=NULL,last_synced_term=NULL WHERE user_id=%s""", (user_id,))
    user_cache.invalidate_user(user_id)
    return {"schedule_id": payload["schedules"][0]["id"], "restored": True}
