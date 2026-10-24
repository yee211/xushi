"""Durable per-user peer refresh batches, claimed with short database leases."""
import json
import logging
import uuid

from fastapi import HTTPException

from ..db import connect
from . import academic, academic_others, academic_runtime

logger = logging.getLogger(__name__)
ACTIVE_STALE_SECONDS = 900
RETENTION_DAYS = 30
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS academic_other_sync_jobs (
        id UUID PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'queued', items JSONB NOT NULL,
        lease_token UUID, leased_until TIMESTAMPTZ,
        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_other_jobs_active_user ON academic_other_sync_jobs(user_id)
        WHERE state IN ('queued','running')""",
    """CREATE INDEX IF NOT EXISTS idx_other_jobs_user_created
        ON academic_other_sync_jobs(user_id, created_at DESC)""",
)


def public_job(row):
    if not row:
        return None
    items = row["items"]
    return {"id": str(row["id"]), "state": row["state"], "total": len(items),
            "done": sum(i["state"] != "pending" for i in items),
            **{state: sum(i["state"] == state for i in items) for state in ("updated", "failed", "skipped")},
            "items": items, "updated_at": row["updated_at"]}


def _expire_stale(db, user_id):
    """Release a user blocked by a batch whose worker/lease disappeared."""
    row = db.execute("""SELECT * FROM academic_other_sync_jobs
        WHERE user_id=%s AND state IN ('queued','running')
        AND updated_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
        AND (leased_until IS NULL OR leased_until < CURRENT_TIMESTAMP)
        FOR UPDATE SKIP LOCKED""", (user_id, ACTIVE_STALE_SECONDS)).fetchone()
    if not row:
        return
    items = [dict(item) for item in row["items"]]
    for item in items:
        if item["state"] == "pending":
            item.update(state="failed", error="sync_timeout", message="同步任务超时，请重新发起同步")
    db.execute("""UPDATE academic_other_sync_jobs SET state='failed',items=%s::jsonb,
        lease_token=NULL,leased_until=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (json.dumps(items, ensure_ascii=False), row["id"]))
    logger.warning("Expired stale peer sync job %s for user %s", row["id"], user_id)


def read(user_id, job_id=None):
    with connect() as db:
        _expire_stale(db, user_id)
        if job_id:
            row = db.execute("SELECT * FROM academic_other_sync_jobs WHERE user_id=%s AND id=%s", (user_id, job_id)).fetchone()
            if not row:
                raise HTTPException(404, "同步任务不存在")
        else:
            row = db.execute("""SELECT * FROM academic_other_sync_jobs WHERE user_id=%s
                ORDER BY created_at DESC LIMIT 1""", (user_id,)).fetchone()
    return public_job(row)


def enqueue(user_id, retry_of=None, *, student_ids=None):
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{user_id}:academic-others",))
        _expire_stale(db, user_id)
        active = db.execute("SELECT * FROM academic_other_sync_jobs WHERE user_id=%s AND state IN ('queued','running')", (user_id,)).fetchone()
        if active:
            requested_ids = set(student_ids) if student_ids is not None else {
                r["student_id"] for r in db.execute(
                    "SELECT student_id FROM academic_others WHERE user_id=%s", (user_id,)).fetchall()}
            if {i["student_id"] for i in active["items"]} != requested_ids:
                raise HTTPException(409, "已有其他同学课表同步任务，请等待完成后再同步指定同学")
            return public_job(active)
        academic_others.check_query_limit(user_id)
        db.execute("""DELETE FROM academic_other_sync_jobs WHERE user_id=%s AND state IN ('completed','failed')
            AND created_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""", (user_id, RETENTION_DAYS))
        retry_ids = None
        if retry_of:
            previous = db.execute("SELECT * FROM academic_other_sync_jobs WHERE user_id=%s AND id=%s", (user_id, retry_of)).fetchone()
            if not previous:
                raise HTTPException(404, "同步任务不存在")
            retry_ids = {i["student_id"] for i in previous["items"] if i["state"] == "failed"}
        rows = db.execute("SELECT * FROM academic_others WHERE user_id=%s ORDER BY student_id", (user_id,)).fetchall()
        items = [{"student_id": r["student_id"], "term": r["term"], "updated_at": str(r["updated_at"]),
                  "name": academic_others._person_meta(r)["display_name"], "state": "pending"}
                 for r in rows if (retry_ids is None or r["student_id"] in retry_ids)
                 and (student_ids is None or r["student_id"] in student_ids)]
        if not items:
            raise HTTPException(409, "没有可同步的已保存课表" if retry_ids is None else "没有可重试的失败课表")
        row = db.execute("INSERT INTO academic_other_sync_jobs(id,user_id,items) VALUES(%s,%s,%s::jsonb) RETURNING *",
                         (uuid.uuid4(), user_id, json.dumps(items, ensure_ascii=False))).fetchone()
    return public_job(row)


def process_one():
    token = uuid.uuid4()
    with connect() as db:
        row = db.execute("""SELECT * FROM academic_other_sync_jobs
            WHERE state IN ('queued','running') AND available_at<=CURRENT_TIMESTAMP
            AND (leased_until IS NULL OR leased_until<CURRENT_TIMESTAMP)
            ORDER BY available_at,created_at FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if not row:
            return False
        db.execute("""UPDATE academic_other_sync_jobs SET state='running',lease_token=%s,
            leased_until=CURRENT_TIMESTAMP+INTERVAL '120 seconds' WHERE id=%s""", (token, row["id"]))
    items = row["items"]
    item = next((i for i in items if i["state"] == "pending"), None)
    if item is None:
        # A job can only reach this state after a partial/manual write; close it
        # instead of raising StopIteration on every worker pass.
        with connect() as db:
            db.execute("""UPDATE academic_other_sync_jobs SET state='completed',lease_token=NULL,leased_until=NULL,
                updated_at=CURRENT_TIMESTAMP WHERE id=%s AND lease_token=%s""", (row["id"], token))
        return True
    deferred = False
    try:
        with academic_runtime.execution(55):
            academic_others.refresh_saved(row["user_id"], item["student_id"], expected=item)
        item["state"] = "updated"
    except academic.AcademicError as error:
        if error.code == "too_many_queries":
            deferred = True  # Don't consume a per-user limit as a failed refresh.
        else:
            item.update(state="skipped" if error.code == "saved_person_changed" else "failed",
                        error=error.code, message=error.message)
    except Exception:
        logger.exception("Peer timetable refresh failed")
        item.update(state="failed", error="refresh_failed", message="同步失败，原课表已保留，请稍后重试")
    state = "running" if any(i["state"] == "pending" for i in items) else "completed"
    with connect() as db:
        db.execute("""UPDATE academic_other_sync_jobs SET items=%s::jsonb,state=%s,lease_token=NULL,leased_until=NULL,
            available_at=CURRENT_TIMESTAMP+(%s*INTERVAL '1 second'),updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND lease_token=%s""", (json.dumps(items, ensure_ascii=False), state, 10 if deferred else 6, row["id"], token))
    return True
