"""Durable, single-leader school sync queue and Shanghai midnight scheduler."""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from ..db import connect
from . import academic, academic_binding, academic_runtime, academic_sync_notifications, academic_sync_requests

logger = logging.getLogger(__name__)
SHANGHAI = timezone(timedelta(hours=8))
LEADER_KEY = 719802601
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS academic_sync_jobs (
        id UUID PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        student_id TEXT NOT NULL,binding_revision BIGINT NOT NULL,binding_updated_at TIMESTAMPTZ NOT NULL,
        term TEXT NOT NULL,refresh BOOLEAN NOT NULL DEFAULT FALSE,source TEXT NOT NULL DEFAULT 'manual',
        state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),
        attempts INTEGER NOT NULL DEFAULT 0,result JSONB,error TEXT,
        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    academic_sync_requests.SCHEMA,
    "ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS phase TEXT NOT NULL DEFAULT 'queued'",
    "ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_jobs_active_user ON academic_sync_jobs(user_id)
        WHERE state IN ('queued','running')""",
    "CREATE INDEX IF NOT EXISTS idx_academic_jobs_pending ON academic_sync_jobs(state,available_at,created_at)",
    "CREATE TABLE IF NOT EXISTS academic_sync_control(id INTEGER PRIMARY KEY CHECK(id=1),pause_until TIMESTAMPTZ)",
    "INSERT INTO academic_sync_control(id) VALUES(1) ON CONFLICT DO NOTHING",
    "CREATE TABLE IF NOT EXISTS academic_sync_days(run_date DATE PRIMARY KEY,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)",
)
_stop = threading.Event()
_thread = None
_scheduler_thread = None
_notification_thread = None


def init_schema():
    with connect() as db:
        for sql in (*SCHEMA, *academic_sync_notifications.SCHEMA):
            db.execute(sql)
        db.execute(academic_sync_requests.BACKFILL)


def public_job(row):
    if not row:
        return None
    result = {key: row[key] for key in ('id','term','state','attempts','result','error','created_at','updated_at','phase','started_at')}
    result["error_code"] = row.get("error_code")
    return result


def read(user_id, job_id=None):
    with connect() as db:
        if job_id:
            row = db.execute("SELECT * FROM academic_sync_jobs WHERE user_id=%s AND id=%s", (user_id, job_id)).fetchone()
            if not row:
                raise HTTPException(404, "同步任务不存在")
        else:
            row = db.execute("SELECT * FROM academic_sync_jobs WHERE user_id=%s ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
    return public_job(row)


def enqueue(user_id, term, refresh=False, *, cooldown_seconds=0, notification_target=None):
    with connect() as db:
        def finish(row):
            result = public_job(row)
            if academic_sync_requests.supported(notification_target):
                academic_sync_requests.remember(db, user_id, notification_target, row["id"])
            if notification_target:
                result["notification_registered"] = academic_sync_notifications.subscribe(db, row, notification_target)
                if notification_target.get("followup"):
                    result["followup_registered"] = result["notification_registered"]
            return result

        academic_binding.lock_user(db, user_id)
        binding = db.execute("SELECT student,revision,updated_at FROM academic_bindings WHERE user_id=%s FOR UPDATE", (user_id,)).fetchone()
        if not binding:
            raise HTTPException(409, "请先绑定学校身份")
        if academic_sync_requests.supported(notification_target):
            prior = academic_sync_requests.find(db, user_id, notification_target)
            if prior:
                if (prior["student_id"] != binding["student"]["id"]
                        or prior["binding_revision"] != binding["revision"]
                        or prior["binding_updated_at"] != binding["updated_at"] or prior["term"] != term
                        or (refresh and not prior["refresh"])):
                    raise HTTPException(409, "原消息对应的同步条件已变更，请发送新的同步请求")
                return finish(prior)
        active = db.execute("SELECT * FROM academic_sync_jobs WHERE user_id=%s AND state IN ('queued','running')", (user_id,)).fetchone()
        if active:
            if (active['student_id'] == binding['student']['id'] and active['binding_revision'] == binding['revision']
                    and active['binding_updated_at'] == binding['updated_at'] and active['term'] == term
                    and (not refresh or active['refresh'])):
                return finish(active)
            raise HTTPException(409, "已有同步任务，请等待完成后重试")
        if cooldown_seconds:
            recent = db.execute("""SELECT * FROM academic_sync_jobs WHERE user_id=%s
                AND student_id=%s AND binding_revision=%s AND binding_updated_at=%s AND term=%s
                AND created_at > CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
                ORDER BY created_at DESC LIMIT 1""", (user_id, binding['student']['id'],
                binding['revision'], binding['updated_at'], term, cooldown_seconds)).fetchone()
            if recent:
                return finish(recent)
        row = db.execute("""INSERT INTO academic_sync_jobs(id,user_id,student_id,binding_revision,binding_updated_at,term,refresh)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) WHERE state IN ('queued','running') DO NOTHING RETURNING *""", (uuid.uuid4(), user_id, binding['student']['id'],
                binding['revision'], binding['updated_at'], term, refresh)).fetchone()
        if not row:
            row = db.execute("SELECT * FROM academic_sync_jobs WHERE user_id=%s AND state IN ('queued','running')", (user_id,)).fetchone()
            if not row or row['term'] != term or (refresh and not row['refresh']):
                raise HTTPException(409, "已有同步任务，请等待完成后重试")
        return finish(row)


def daily(db, now=None):
    """Catch up once on startup; after that enqueue at each Shanghai date boundary."""
    day = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).date()
    inserted = db.execute("INSERT INTO academic_sync_days(run_date) VALUES(%s) ON CONFLICT DO NOTHING RETURNING run_date", (day,)).fetchone()
    if not inserted:
        return
    db.execute("""INSERT INTO academic_sync_jobs(id,user_id,student_id,binding_revision,binding_updated_at,term,refresh,source)
        SELECT gen_random_uuid(),user_id,student->>'id',revision,updated_at,
            COALESCE(last_synced_term,student->>'default_term'),TRUE,'daily'
        FROM academic_bindings WHERE COALESCE(last_synced_term,student->>'default_term') ~ '^[0-9]{4}-[0-9]{4}-[12]$'
        ON CONFLICT(user_id) WHERE state IN ('queued','running') DO NOTHING""")
    # Retain recent task outcomes for resume/support, without keeping old timetables.
    db.execute("DELETE FROM academic_sync_jobs WHERE state IN ('succeeded','failed') AND updated_at < CURRENT_TIMESTAMP - INTERVAL '30 days'")
    db.execute("DELETE FROM academic_sync_days WHERE run_date < %s - INTERVAL '60 days'", (day,))


def execute_job(job):
    return academic_binding.sync(job['user_id'], job['term'], job['refresh'],
        expected_binding=(job['student_id'], job['binding_revision'], job['binding_updated_at']))


def process_one(db):
    # A session advisory lock stays held even while this connection commits and
    # the school query uses a separate transaction. Only one process fetches jobs.
    if not db.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (LEADER_KEY,)).fetchone()['acquired']:
        db.commit()
        return False
    db.commit()
    try:
        # The advisory lock proves there is no other live executor.
        db.execute("""UPDATE academic_sync_jobs SET
            state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
            phase=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
            error=CASE WHEN attempts>=3 THEN '同步多次中断，请重新发起同步' ELSE error END,
            error_code=CASE WHEN attempts>=3 THEN 'worker_interrupted' ELSE error_code END,
            updated_at=CURRENT_TIMESTAMP WHERE state='running'""")
        paused = db.execute("SELECT 1 FROM academic_sync_control WHERE pause_until>CURRENT_TIMESTAMP").fetchone()
        if paused:
            db.commit()
            return False
        job = db.execute("""UPDATE academic_sync_jobs SET state='running',phase='querying',started_at=CURRENT_TIMESTAMP,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP
            WHERE id=(SELECT id FROM academic_sync_jobs WHERE state='queued' AND available_at<=CURRENT_TIMESTAMP
                ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *""").fetchone()
        db.commit()
        if not job:
            return False
        def progress(phase):
            db.execute("UPDATE academic_sync_jobs SET phase=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND state='running'",
                       (phase, job['id']))
            db.commit()
            logger.info("School sync phase: %s %s", job['id'], phase)

        try:
            with academic_runtime.execution(90, progress):
                result = execute_job(job)
        except (academic.AcademicError, HTTPException, academic_runtime.SyncTimeout) as error:
            status = 504 if isinstance(error, academic_runtime.SyncTimeout) else (
                error.status if isinstance(error, academic.AcademicError) else error.status_code)
            message = str(error) if isinstance(error, academic_runtime.SyncTimeout) else (
                error.message if isinstance(error, academic.AcademicError) else str(error.detail))
            retry = status in (429,502,503,504) and job['attempts'] < 3
            if isinstance(error, academic.AcademicError) and error.code == 'connection_expired':
                try:
                    from . import academic_mail
                    academic_mail.connection_event("query_unavailable")
                except Exception:
                    logger.warning("School query failure notification unavailable")
            if (isinstance(error, academic.AcademicError) and error.code == 'connection_expired') or '学校连接暂不可用' in message:
                db.execute("UPDATE academic_sync_control SET pause_until=CURRENT_TIMESTAMP + INTERVAL '60 seconds' WHERE id=1")
            db.execute("""UPDATE academic_sync_jobs SET state=%s,phase=%s,error=%s,error_code=%s,
                available_at=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),updated_at=CURRENT_TIMESTAMP WHERE id=%s AND state='running'""",
                ('queued' if retry else 'failed', 'retrying' if retry else 'failed', message, academic_sync_notifications.classify_error(error), 10 * 2 ** job['attempts'], job['id']))
        except Exception:
            logger.exception("School sync job failed: %s", job['id'])
            db.execute("UPDATE academic_sync_jobs SET state='failed',phase='failed',error=%s,error_code='internal_error',updated_at=CURRENT_TIMESTAMP WHERE id=%s AND state='running'",
                ("同步失败，请稍后重试；原课表已保留", job['id']))
        else:
            db.execute("""UPDATE academic_sync_jobs SET state='succeeded',phase='completed',result=%s::jsonb,error=NULL,error_code=NULL,
                updated_at=CURRENT_TIMESTAMP WHERE id=%s AND state='running'""", (json.dumps(jsonable_encoder({key: value for key, value in result.items() if key in (
                    'schedule_id','name','term','imported','replaced','unchanged','last_synced_at','warnings',
                    'overwrite_policy','binding_revision','fetched_at','completed_weeks','expected_weeks','cached','completeness')}), ensure_ascii=False), job['id']))
        db.commit()
        return True
    finally:
        db.rollback()
        db.execute("SELECT pg_advisory_unlock(%s)", (LEADER_KEY,))
        db.commit()


def run():
    while not _stop.is_set():
        try:
            with connect() as db:
                worked = process_one(db)
        except Exception:
            logger.exception("School sync worker unavailable")
            worked = False
        _stop.wait(0.2 if worked else 1)


def run_notifications():
    while not _stop.is_set():
        try:
            worked = academic_sync_notifications.dispatch_one()
        except Exception:
            logger.exception("School sync notification worker unavailable")
            worked = False
        _stop.wait(0.2 if worked else 1)


def run_scheduler():
    last_day = None
    while not _stop.is_set():
        day = datetime.now(SHANGHAI).date()
        if day != last_day:
            try:
                with connect() as db:
                    daily(db)
                last_day = day
            except Exception:
                logger.exception("School midnight scheduler unavailable")
                _stop.wait(10)
        _stop.wait(1)


def start():
    global _thread, _scheduler_thread, _notification_thread
    init_schema()
    if os.getenv('ACADEMIC_SYNC_WORKER_ENABLED', 'true').lower() not in ('1','true','yes'):
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=run, name='school-sync', daemon=True)
    _thread.start()
    _scheduler_thread = threading.Thread(target=run_scheduler, name='school-midnight', daemon=True)
    _scheduler_thread.start()
    _notification_thread = threading.Thread(target=run_notifications, name="school-sync-notify", daemon=True)
    _notification_thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=65)
    if _scheduler_thread:
        _scheduler_thread.join(timeout=2)
    if _notification_thread:
        _notification_thread.join(timeout=20)



def enqueue_all():
    """Admin-requested fresh sync; active users are skipped atomically."""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) AS count FROM academic_bindings").fetchone()['count']
        rows = db.execute("""INSERT INTO academic_sync_jobs(id,user_id,student_id,binding_revision,binding_updated_at,term,refresh,source)
            SELECT gen_random_uuid(),user_id,student->>'id',revision,updated_at,
                COALESCE(last_synced_term,student->>'default_term'),TRUE,'admin'
            FROM academic_bindings WHERE COALESCE(last_synced_term,student->>'default_term') ~ '^[0-9]{4}-[0-9]{4}-[12]$'
            ON CONFLICT(user_id) WHERE state IN ('queued','running') DO NOTHING RETURNING id""").fetchall()
    return {"enqueued": len(rows), "skipped": total-len(rows), "total": total}
