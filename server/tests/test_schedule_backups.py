"""Real PostgreSQL recovery tests in a disposable schema, with no school access."""
import os
import uuid
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app.db import connect as real_connect
from app.db import schema as db_schema
from app.services import academic_binding, academic_jobs, schedule_backups

pytestmark = pytest.mark.skipif(os.getenv("TEST_ACADEMIC_QUEUE_DB") != "1", reason="Requires local PostgreSQL")


@pytest.fixture
def database(monkeypatch):
    name = "test_recovery_" + uuid.uuid4().hex
    with real_connect() as db:
        db.execute("CREATE SCHEMA " + name)
    @contextmanager
    def isolated():
        with real_connect() as db:
            db.execute("SELECT set_config('search_path',%s,true)", (name,))
            yield db
    monkeypatch.setattr(db_schema, "connect", isolated)
    monkeypatch.setattr(schedule_backups, "connect", isolated)
    monkeypatch.setattr(academic_binding, "connect", isolated)
    monkeypatch.setattr(academic_jobs, "connect", isolated)
    try:
        db_schema.init_db()
        academic_jobs.init_schema()
        with isolated() as db:
            user = db.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
            original = db.execute("INSERT INTO schedules(user_id,name,term,variant_type) VALUES(%s,'old','old','original') RETURNING id", (user,)).fetchone()["id"]
            adjusted = db.execute("INSERT INTO schedules(user_id,name,source_schedule_id,variant_type) VALUES(%s,'adjusted',%s,'adjusted') RETURNING id", (user, original)).fetchone()["id"]
            course = db.execute("""INSERT INTO courses(schedule_id,name,weekday,start_section,end_section,weeks)
                VALUES(%s,'test',1,1,2,'[1,2]') RETURNING id""", (original,)).fetchone()["id"]
            db.execute("""INSERT INTO courses(schedule_id,name,weekday,start_section,end_section,source_course_id)
                VALUES(%s,'linked',2,3,4,%s)""", (adjusted, course))
            db.execute("INSERT INTO course_adjustments(course_id,week,weekday,start_section,end_section) VALUES(%s,1,2,3,4)", (course,))
            db.execute("""INSERT INTO course_change_logs(schedule_id,course_id,action_type,title,details)
                VALUES(%s,%s,'manual_edit','test','[{"course_id":1}]')""", (original, course))
        yield isolated, user, original, course
    finally:
        with real_connect() as db:
            db.execute("DROP SCHEMA " + name + " CASCADE")


def test_restore_preserves_courses_adjustments_logs_and_links(database):
    connect, user, original, course = database
    with connect() as db:
        backup = schedule_backups.capture(db, user)
        expected = db.execute("SELECT payload FROM schedule_backups WHERE id=%s", (backup,)).fetchone()["payload"]
        db.execute("DELETE FROM schedules WHERE user_id=%s", (user,))
        db.execute("INSERT INTO schedules(user_id,name) VALUES(%s,'new')", (user,))
    result = schedule_backups.restore(user, backup)
    assert result["restored"]
    with connect() as db:
        for table in schedule_backups.TABLES:
            rows = db.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
            from fastapi.encoders import jsonable_encoder
            assert jsonable_encoder(rows) == expected[table]
        # Restoring also captured the replacement, so recovery can itself be undone.
        latest = db.execute("SELECT payload FROM schedule_backups WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user,)).fetchone()["payload"]
        assert latest["schedules"][0]["name"] == "new"


def test_backup_retention_and_ownership(database):
    connect, user, original, course = database
    with connect() as db:
        for _ in range(7):
            schedule_backups.capture(db, user)
        other = db.execute("INSERT INTO users(username) VALUES('other') RETURNING id").fetchone()["id"]
    backups = schedule_backups.list_backups(user)["backups"]
    assert len(backups) == 5
    assert schedule_backups.list_backups(other) == {"backups": []}
    with pytest.raises(HTTPException) as error:
        schedule_backups.restore(other, backups[0]["id"])
    assert error.value.status_code == 404


def test_restore_refuses_active_sync_and_rolls_back_failed_insert(database, monkeypatch):
    connect, user, original, course = database
    with connect() as db:
        backup = schedule_backups.capture(db, user)
        db.execute("""INSERT INTO academic_sync_jobs(id,user_id,student_id,binding_revision,binding_updated_at,term)
            VALUES(%s,%s,'student01',1,now(),'2026-2027-1')""", (uuid.uuid4(), user))
    with pytest.raises(HTTPException) as error:
        schedule_backups.restore(user, backup)
    assert error.value.status_code == 409
    with connect() as db:
        db.execute("UPDATE academic_sync_jobs SET state='failed'")
        # Deliberately break a snapshot FK to verify recovery is atomic.
        db.execute("""UPDATE schedule_backups SET payload=jsonb_set(payload,'{course_adjustments,0,course_id}','99999999') WHERE id=%s""", (backup,))
    import psycopg
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        schedule_backups.restore(user, backup)
    with connect() as db:
        assert db.execute("SELECT name FROM schedules WHERE id=%s", (original,)).fetchone()["name"] == "old"
        assert db.execute("SELECT 1 FROM courses WHERE id=%s", (course,)).fetchone()


def test_ordinary_import_captures_adjustments_before_overwrite(database):
    from app.services.schedule_import import write_schedule
    connect, user, original, course = database
    with connect() as db:
        result = write_schedule(db, user_id=user, overwrite=True, target_schedule_id=original,
            parsed={'name': 'replacement', 'term': 'old', 'courses': [
                {'name': 'new', 'weekday': 1, 'start_section': 1, 'end_section': 2, 'weeks': [1]}]})
        backup = db.execute('SELECT id,payload FROM schedule_backups WHERE user_id=%s ORDER BY id DESC LIMIT 1', (user,)).fetchone()
        assert any(item['course_id'] == course for item in backup['payload']['course_adjustments'])
        assert result['replaced']
    schedule_backups.restore(user, backup['id'])
    with connect() as db:
        assert db.execute('SELECT 1 FROM course_adjustments WHERE course_id=%s', (course,)).fetchone()


def test_background_retry_budgets_use_real_database(database):
    from datetime import date

    from app.channels.weixin.store import claim_message, complete_message
    from app.services.daily_push import _record_push_result
    connect, user, original, course = database
    with connect() as db:
        for _ in range(3):
            assert claim_message(db, 'test-bot', 'poison-message')
            complete_message(db, 'test-bot', 'poison-message', 'permanent error')
        assert not claim_message(db, 'test-bot', 'poison-message')
        for _ in range(3):
            _record_push_result(db, user, date(2026, 10, 9), 'failed', 'weather error')
        log = db.execute('SELECT attempts FROM daily_push_logs WHERE user_id=%s', (user,)).fetchone()
        assert log['attempts'] == 3
