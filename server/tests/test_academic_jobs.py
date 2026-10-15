"""Real PostgreSQL queue tests in a disposable schema
no school requests."""
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.db import connect as real_connect
from app.services import academic, academic_binding
from app.services import academic_jobs as jobs

pytestmark = pytest.mark.skipif(os.getenv('TEST_ACADEMIC_QUEUE_DB') != '1', reason='Requires local PostgreSQL with mocked school upstream')


@pytest.fixture
def queue(monkeypatch):
    schema = 'test_school_jobs_' + uuid.uuid4().hex
    with real_connect() as db:
        db.execute('CREATE SCHEMA ' + schema)
    # Worker commits repeatedly: use session search_path rather than SET LOCAL.
    @contextmanager
    def isolated():
        with real_connect() as db:
            db.execute("SELECT set_config('search_path',%s,false)", (schema,))
            try:
                yield db
                db.commit()
            finally:
                db.rollback()
                db.execute("RESET search_path")
                db.commit()
    monkeypatch.setattr(jobs, 'connect', isolated)
    monkeypatch.setattr(academic_binding, 'connect', isolated)
    try:
        with isolated() as db:
            db.execute('CREATE TABLE users(id BIGINT PRIMARY KEY)')
            db.execute('INSERT INTO users VALUES(1),(2),(3)')
            db.execute("""CREATE TABLE academic_bindings(user_id BIGINT PRIMARY KEY REFERENCES users(id),student JSONB,
                revision BIGINT DEFAULT 1,updated_at TIMESTAMPTZ DEFAULT now(),last_synced_at TIMESTAMPTZ,last_synced_term TEXT)""")
            db.execute("""INSERT INTO academic_bindings(user_id,student) VALUES
                (1,'{"id":"student01","name":"test","default_term":"2026-2027-1"}'),
                (2,'{"id":"student02","name":"test","default_term":"2026-2027-1"}')""")
            db.commit()
        jobs.init_schema()
        with isolated() as db:
            db.execute('INSERT INTO academic_sync_days(run_date) VALUES(%s)', (datetime.now(jobs.SHANGHAI).date(),))
            db.commit()
        yield isolated
    finally:
        with real_connect() as db:
            db.execute('DROP SCHEMA ' + schema + ' CASCADE')


def test_enqueue_deduplicates_and_enforces_ownership(queue):
    task = jobs.enqueue(1, '2026-2027-1')
    assert jobs.enqueue(1, '2026-2027-1')['id'] == task['id']
    assert jobs.read(1)['id'] == task['id']
    with pytest.raises(HTTPException) as exc:
        jobs.read(2, task['id'])
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        jobs.enqueue(1, '2026-2027-2')
    with pytest.raises(HTTPException):
        jobs.enqueue(3, '2026-2027-1')


def test_worker_single_leader_and_success(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    calls = []
    monkeypatch.setattr(jobs, 'execute_job', lambda job: calls.append(job['id']) or {'schedule_id': 10})
    with queue() as leader, queue() as follower:
        leader.execute('SELECT pg_advisory_lock(%s)', (jobs.LEADER_KEY,))
        leader.commit()
        try:
            assert not jobs.process_one(follower)
            assert not calls
        finally:
            leader.execute('SELECT pg_advisory_unlock(%s)', (jobs.LEADER_KEY,))
            leader.commit()
        assert jobs.process_one(follower)
    assert jobs.read(1, task['id'])['result'] == {'schedule_id': 10}
    assert len(calls) == 1


def test_restart_recovers_running_job(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    with queue() as db:
        db.execute("UPDATE academic_sync_jobs SET state='running' WHERE id=%s", (task['id'],))
        db.commit()
    monkeypatch.setattr(jobs, 'execute_job', lambda job: {'schedule_id': 11})
    with queue() as db:
        assert jobs.process_one(db)
    assert jobs.read(1, task['id'])['state'] == 'succeeded'


def test_daily_midnight_deduplication_and_default_term(queue):
    midnight = (datetime.now(jobs.SHANGHAI) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    with queue() as db:
        jobs.daily(db, midnight)
        db.commit()
        jobs.daily(db, midnight)
        db.commit()
        rows = db.execute('SELECT * FROM academic_sync_jobs').fetchall()
    assert len(rows) == 2
    assert all(row['source'] == 'daily' and row['refresh'] for row in rows)
    assert {row['user_id'] for row in rows} == {1,2}


def test_queued_job_rejects_changed_binding_without_school_request(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    with queue() as db:
        db.execute('UPDATE academic_bindings SET revision=revision+1 WHERE user_id=1')
        db.commit()
    monkeypatch.setattr(academic, 'get_schedule', lambda *args: pytest.fail('must not call school after rebind'))
    with queue() as db:
        assert jobs.process_one(db)
    result = jobs.read(1, task['id'])
    assert result['state'] == 'failed' and '绑定已变更' in result['error']


def test_transient_retry_is_bounded_and_failure_preserves_result(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    def fail(job):
        raise academic.AcademicError('upstream_failed', '学校暂不可用', 503)
    monkeypatch.setattr(jobs, 'execute_job', fail)
    for attempt in range(1,4):
        with queue() as db:
            db.execute('UPDATE academic_sync_jobs SET available_at=now()')
            db.commit()
            assert jobs.process_one(db)
        result = jobs.read(1, task['id'])
        assert result['attempts'] == attempt
        assert result['state'] == ('failed' if attempt == 3 else 'queued')
    assert result['result'] is None



def test_expired_connection_pauses_remaining_queue(queue, monkeypatch):
    first = jobs.enqueue(1, '2026-2027-1')
    second = jobs.enqueue(2, '2026-2027-1')
    def expired(job):
        raise academic.AcademicError('connection_expired', '学校登录已过期', 409)
    monkeypatch.setattr(jobs, 'execute_job', expired)
    with queue() as db:
        assert jobs.process_one(db)
        assert not jobs.process_one(db)
    assert jobs.read(1, first['id'])['state'] == 'failed'
    assert jobs.read(2, second['id'])['state'] == 'queued'


def test_task_outcome_does_not_retain_old_timetable_courses(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    monkeypatch.setattr(jobs, 'execute_job', lambda job: {'schedule_id': 10, 'courses': [{'name': 'old'}], 'student': {'name': 'private'}})
    with queue() as db:
        assert jobs.process_one(db)
    assert jobs.read(1, task['id'])['result'] == {'schedule_id': 10}



def test_midnight_scheduler_runs_even_while_sync_executor_is_busy(queue):
    midnight = (datetime.now(jobs.SHANGHAI) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    with queue() as executor, queue() as scheduler:
        executor.execute('SELECT pg_advisory_lock(%s)', (jobs.LEADER_KEY,))
        executor.commit()
        try:
            jobs.daily(scheduler, midnight)
            scheduler.commit()
            assert scheduler.execute('SELECT COUNT(*) AS count FROM academic_sync_jobs').fetchone()['count'] == 2
        finally:
            executor.execute('SELECT pg_advisory_unlock(%s)', (jobs.LEADER_KEY,))
            executor.commit()



def test_admin_sync_all_skips_active_and_does_not_consume_daily_batch(queue):
    existing = jobs.enqueue(1, '2026-2027-1')
    result = jobs.enqueue_all()
    assert result == {'enqueued': 1, 'skipped': 1, 'total': 2}
    assert jobs.enqueue_all()['enqueued'] == 0
    assert jobs.read(1)['id'] == existing['id']
    with queue() as db:
        row = db.execute("SELECT source,refresh FROM academic_sync_jobs WHERE user_id=2").fetchone()
        assert row['source'] == 'admin' and row['refresh']
        assert db.execute('SELECT COUNT(*) AS count FROM academic_sync_days').fetchone()['count'] == 1


def test_restart_does_not_retry_exhausted_job(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')
    with queue() as db:
        db.execute("UPDATE academic_sync_jobs SET state='running',attempts=3 WHERE id=%s", (task['id'],))
    monkeypatch.setattr(jobs, 'execute_job', lambda job: pytest.fail("exhausted job executed"))
    with queue() as db:
        assert not jobs.process_one(db)
    assert jobs.read(1, task['id'])['state'] == 'failed'


def test_timeout_retries_and_exposes_progress(queue, monkeypatch):
    task = jobs.enqueue(1, '2026-2027-1')

    def timeout(job):
        from app.services import academic_runtime
        academic_runtime.stage('writing')
        raise academic_runtime.SyncTimeout("同步执行超时，原课表已保留")

    monkeypatch.setattr(jobs, 'execute_job', timeout)
    with queue() as db:
        assert jobs.process_one(db)
    result = jobs.read(1, task['id'])
    assert result['state'] == 'queued'
    assert result['phase'] == 'retrying'
    assert result['started_at']
    assert "超时" in result['error']


@pytest.fixture
def notification_queue(queue, monkeypatch):
    from app.services import academic_sync_notifications as notices

    monkeypatch.setattr(notices, "connect", queue)
    with queue() as db:
        db.execute("""CREATE TABLE channel_messages(provider TEXT,account_id TEXT,message_id TEXT,status TEXT,
            attempts INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(provider,account_id,message_id))""")
        db.execute("INSERT INTO channel_messages(provider,account_id,message_id,status) VALUES('weixin_ilink','bot','m1','processing')")
    return queue, notices


def notification_target():
    return {"provider": "weixin_ilink", "sender_id": "sender", "account_id": "bot", "message_id": "m1"}


def test_completion_waits_for_initial_reply_and_deduplicates(notification_queue, monkeypatch):
    queue, notices = notification_queue
    task = jobs.enqueue(1, '2026-2027-1', True, notification_target=notification_target())
    assert task['notification_registered']
    again = jobs.enqueue(1, '2026-2027-1', True, notification_target=notification_target())
    assert again['id'] == task['id']
    monkeypatch.setattr(jobs, 'execute_job', lambda job: {'unchanged': True})
    with queue() as db:
        assert jobs.process_one(db)
        assert notices.claim(db) is None  # Completed before the initial reply is sent.
        assert db.execute('SELECT COUNT(*) AS count FROM academic_sync_notifications').fetchone()['count'] == 1
        db.execute("UPDATE channel_messages SET status='done'")
    with queue() as first, queue() as second:
        row, result = notices.claim(first)
        assert result['state'] == 'succeeded'
        assert notices.claim(second) is None  # Row remains locked by first's transaction.
    notices.finish(row, 'sent')
    with queue() as db:
        assert notices.claim(db) is None
        assert db.execute('SELECT state FROM academic_sync_notifications').fetchone()['state'] == 'sent'


def test_transient_failure_waits_until_final_failure(notification_queue, monkeypatch):
    queue, notices = notification_queue
    task = jobs.enqueue(1, '2026-2027-1', True, notification_target=notification_target())
    def fail(job):
        raise academic.AcademicError('upstream_timeout', '学校查询超时', 504)
    monkeypatch.setattr(jobs, 'execute_job', fail)
    with queue() as db:
        db.execute("UPDATE channel_messages SET status='done'")
        db.commit()
        assert jobs.process_one(db)
        assert notices.claim(db) is None
        db.execute("UPDATE academic_sync_jobs SET attempts=2,available_at=now() WHERE id=%s", (task['id'],))
        db.commit()
        assert jobs.process_one(db)
        row, result = notices.claim(db)
        assert result['state'] == 'failed' and result['error_code'] == 'upstream_timeout'
        assert '查询超时' in notices.completion_text(result)


def test_notification_recovers_lease_and_rejects_stale_owner(notification_queue):
    queue, notices = notification_queue
    task = jobs.enqueue(1, '2026-2027-1', True, notification_target=notification_target())
    with queue() as db:
        db.execute("UPDATE channel_messages SET status='done'")
        db.execute("UPDATE academic_sync_jobs SET state='succeeded' WHERE id=%s", (task['id'],))
        first, _ = notices.claim(db)
        db.execute("UPDATE academic_sync_notifications SET lease_until=now()-INTERVAL '1 second'")
    with queue() as db:
        second, _ = notices.claim(db)
        assert second['id'] == first['id'] and second['lease_id'] != first['lease_id']
        assert second['attempts'] == 2
    notices.finish(first, 'sent')
    with queue() as db:
        assert db.execute('SELECT state FROM academic_sync_notifications').fetchone()['state'] == 'sending'
    notices.finish(second, 'pending', 'delivery_failed')
    with queue() as db:
        assert notices.claim(db) is None  # Delivery retry is delayed.
        db.execute("UPDATE academic_sync_notifications SET available_at=now()")
        third, _ = notices.claim(db)
        assert third['attempts'] == 3
        db.execute("UPDATE academic_sync_notifications SET lease_until=now()-INTERVAL '1 second'")
        assert notices.claim(db) is None
        assert db.execute('SELECT state FROM academic_sync_notifications').fetchone()['state'] == 'failed'


def test_changed_identity_cancels_notification(notification_queue):
    queue, notices = notification_queue
    jobs.enqueue(1, '2026-2027-1', True, notification_target=notification_target())
    with queue() as db:
        db.execute("CREATE TABLE user_identities(user_id BIGINT,provider TEXT,provider_user_id TEXT,account_id TEXT,context_token TEXT)")
        db.execute("CREATE TABLE channel_accounts(provider TEXT,account_id TEXT,status TEXT,bot_token_encrypted TEXT,api_base_url TEXT,admin_user_id TEXT)")
        db.execute("INSERT INTO user_identities VALUES(2,'weixin_ilink','sender','bot','context')")
        db.execute("INSERT INTO channel_accounts VALUES('weixin_ilink','bot','active','encrypted','https://ilinkai.weixin.qq.com','')")
        db.execute("UPDATE channel_messages SET status='done'")
        db.execute("UPDATE academic_sync_jobs SET state='succeeded'")
        row, result = notices.claim(db)
    notices.deliver(row, result)
    with queue() as db:
        assert db.execute('SELECT state FROM academic_sync_notifications').fetchone()['state'] == 'cancelled'
