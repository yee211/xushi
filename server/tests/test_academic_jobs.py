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
