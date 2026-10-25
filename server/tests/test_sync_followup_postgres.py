"""Opt-in integration against an explicitly named localhost test database."""
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from app.agent.sync_followup import prepare
from app.services import academic_jobs
from app.services import academic_sync_followup as continuation
from app.services import academic_sync_notifications as notifications


@pytest.fixture
def database(monkeypatch):
    dsn = os.getenv("XUSHI_FOLLOWUP_TEST_DSN", "")
    if not dsn:
        pytest.skip("dedicated local PostgreSQL not configured")
    parsed = urlsplit(dsn)
    expected_port = int(os.getenv("XUSHI_FOLLOWUP_TEST_PORT", "55439"))
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != expected_port:
        pytest.fail(f"followup integration requires isolated localhost:{expected_port}")
    schema = "followup_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def connect():
        return psycopg.connect(dsn, options="-c search_path=" + schema, row_factory=dict_row)
    monkeypatch.setattr(academic_jobs, "connect", connect)
    monkeypatch.setattr(notifications, "connect", connect)
    monkeypatch.setattr(continuation, "connect", connect)
    try:
        with connect() as db:
            db.execute("CREATE TABLE users(id BIGINT PRIMARY KEY)")
            db.execute("""CREATE TABLE academic_bindings(user_id BIGINT PRIMARY KEY,
                student JSONB,revision BIGINT,updated_at TIMESTAMPTZ)""")
            db.execute("""CREATE TABLE schedules(id BIGINT PRIMARY KEY,user_id BIGINT,name TEXT,term TEXT,
                start_date DATE,end_date DATE,variant_type TEXT,source_schedule_id BIGINT)""")
            db.execute("""CREATE TABLE courses(id BIGINT PRIMARY KEY,schedule_id BIGINT,name TEXT,teacher TEXT,
                room TEXT,weekday INT,start_section INT,end_section INT,weeks INT[])""")
            db.execute("""CREATE TABLE course_adjustments(course_id BIGINT,week INT,weekday INT,
                start_section INT,end_section INT,room TEXT)""")
            db.execute("""CREATE TABLE channel_messages(provider TEXT,account_id TEXT,message_id TEXT,status TEXT,attempts INTEGER NOT NULL DEFAULT 1,reply_text TEXT)""")
            db.execute("""CREATE TABLE user_identities(user_id BIGINT,provider TEXT,provider_user_id TEXT,
                account_id TEXT,context_token TEXT)""")
            db.execute("""CREATE TABLE channel_accounts(provider TEXT,account_id TEXT,status TEXT,
                bot_token_encrypted TEXT,api_base_url TEXT,admin_user_id TEXT)""")
            for statement in (*academic_jobs.SCHEMA, *notifications.SCHEMA):
                db.execute(statement)
            db.execute("INSERT INTO users VALUES(7)")
            db.execute("INSERT INTO academic_bindings VALUES(7,'{\"id\":\"student\"}',3,CURRENT_TIMESTAMP)")
            db.execute("""INSERT INTO schedules VALUES(12,7,'Synthetic','2026-2027-1',
                CURRENT_DATE - 100,CURRENT_DATE + 100,'original',NULL)""")
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            db.execute("INSERT INTO courses VALUES(1,12,'Synthetic course','Teacher','A101',%s,1,2,%s)",
                       (today.isoweekday(), list(range(1, 31))))
            db.execute("INSERT INTO channel_accounts VALUES('weixin_ilink','bot','active','encrypted','https://example.test','')")
            db.execute("INSERT INTO user_identities VALUES(7,'weixin_ilink','sender','bot','context')")
        yield connect
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def submit(connect, message_id="m1"):
    plan = prepare("同步课表，看看今天有什么课", datetime.now(ZoneInfo("Asia/Shanghai")))
    target = {"provider": "weixin_ilink", "sender_id": "sender", "account_id": "bot",
              "message_id": message_id, "followup": plan}
    job = academic_jobs.enqueue(7, "2026-2027-1", True, notification_target=target)
    return job, target


def complete(connect, job):
    with connect() as db:
        db.execute("""UPDATE academic_sync_jobs SET state='succeeded',result='{"schedule_id":12}'
            WHERE id=%s""", (job["id"],))
        db.execute("INSERT INTO channel_messages(provider,account_id,message_id,status) VALUES('weixin_ilink','bot','m1','done')")


def test_subscription_is_transactional_idempotent_and_cannot_be_overwritten(database):
    connect = database
    job, target = submit(connect)
    assert job["followup_registered"]
    # Replay the same event reuses the original frozen plan.
    with connect() as db:
        persisted = db.execute("SELECT followup FROM academic_sync_notifications").fetchone()["followup"]
        assert notifications.subscribe(db, dict(job, user_id=7), dict(target, followup=persisted))
        assert not notifications.subscribe(db, dict(job, user_id=7), dict(target, message_id="m2"))
        notifications.subscribe(db, dict(job, user_id=7), dict(target, message_id="m2", followup=None))
        row = db.execute("SELECT message_id,followup FROM academic_sync_notifications").fetchone()
        assert row["message_id"] == "m1" and row["followup"] == persisted
        assert db.execute("SELECT count(*) AS n FROM academic_sync_notifications").fetchone()["n"] == 1
    # A subscriber registered in a rolled-back transaction is never visible.
    with connect() as db:
        with pytest.raises(RuntimeError):
            with db.transaction():
                notifications.subscribe(db, dict(job, user_id=7), dict(target, sender_id="other"))
                raise RuntimeError("rollback")
        assert db.execute("SELECT count(*) AS n FROM academic_sync_notifications").fetchone()["n"] == 1


def test_restart_after_send_failure_reuses_cached_answer_and_message_id(database, monkeypatch):
    connect = database
    job, _ = submit(connect)
    with connect() as db:
        assert notifications.claim(db) is None
    complete(connect, job)
    client = MagicMock()
    client.send_text.side_effect = TimeoutError("ambiguous send")
    monkeypatch.setattr(notifications, "ILinkClient", lambda *args: client)
    monkeypatch.setattr(notifications, "decrypt_token", lambda value: "synthetic-token")
    assert notifications.dispatch_one()
    first_call = client.send_text.call_args
    assert "08:20–10:00 Synthetic course，Teacher，A101" in first_call.args[1]
    with connect() as db:
        saved = db.execute("SELECT * FROM academic_sync_notifications").fetchone()
        assert saved["state"] == "pending" and saved["delivery_text"] == first_call.args[1]
        db.execute("UPDATE academic_sync_notifications SET available_at=CURRENT_TIMESTAMP")
        db.execute("UPDATE courses SET name='Changed after rendering'")
    # No runtime object survives this boundary. Fresh connections recover all
    # required state from SQL; the graph must not run again for delivery retry.
    query = MagicMock(side_effect=AssertionError("must reuse durable answer"))
    monkeypatch.setattr(continuation, "answer", query)
    client.send_text.side_effect = None
    assert notifications.dispatch_one()
    assert client.send_text.call_args == first_call
    query.assert_not_called()
    assert not notifications.dispatch_one()
    with connect() as db:
        assert db.execute("SELECT state FROM academic_sync_notifications").fetchone()["state"] == "sent"


def test_expired_lease_cannot_send_or_acknowledge_new_owner(database, monkeypatch):
    connect = database
    job, _ = submit(connect)
    complete(connect, job)
    with connect() as db:
        old, old_job = notifications.claim(db)
    with connect() as db:
        db.execute("UPDATE academic_sync_notifications SET lease_until=CURRENT_TIMESTAMP - INTERVAL '1 second'")
    with connect() as db:
        new, _ = notifications.claim(db)
    assert old["lease_id"] != new["lease_id"]
    monkeypatch.setattr(continuation, "delivery_text", lambda *args: "cached")
    client = MagicMock()
    monkeypatch.setattr(notifications, "ILinkClient", lambda *args: client)
    monkeypatch.setattr(notifications, "decrypt_token", lambda value: "synthetic-token")
    notifications.deliver(old, old_job)
    notifications.finish(old, "sent")
    client.send_text.assert_not_called()
    with connect() as db:
        row = db.execute("SELECT * FROM academic_sync_notifications").fetchone()
        assert row["state"] == "sending" and row["lease_id"] == new["lease_id"]


def test_binding_change_prevents_cached_course_delivery(database, monkeypatch):
    connect = database
    job, _ = submit(connect)
    complete(connect, job)
    with connect() as db:
        row, terminal = notifications.claim(db)
        row["delivery_text"] = "private old course"
        db.execute("UPDATE academic_bindings SET revision=4")
    text = continuation.delivery_text(row, terminal)
    assert "绑定或课表已发生变化" in text and "private old course" not in text


def test_schema_upgrade_is_repeatable(database, monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "migrations/versions/0020_sync_followup.py"
    spec = importlib.util.spec_from_file_location("sync_followup_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with database() as db:
        monkeypatch.setattr(migration.op, "execute", db.execute)
        migration.downgrade()
        columns = db.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='academic_sync_notifications'""").fetchall()
        assert not {"followup", "delivery_text"} & {row["column_name"] for row in columns}
        for _ in range(2):
            migration.upgrade()
            for statement in notifications.FOLLOWUP_SCHEMA:
                db.execute(statement)
        assert db.execute("SELECT followup,delivery_text FROM academic_sync_notifications LIMIT 1").fetchone() is None


def test_final_notification_unblocks_after_ack_delivery_exhausted(database):
    connect = database
    job, _ = submit(connect)
    complete(connect, job)
    with connect() as db:
        db.execute("UPDATE channel_messages SET status='failed',attempts=2")
        assert notifications.claim(db) is None
        db.execute("UPDATE channel_messages SET attempts=3")
        claimed = notifications.claim(db)
        assert claimed is not None
        assert claimed[1]["state"] == "succeeded"


def test_reply_survives_connection_restart_without_overwrite(database):
    from app.channels.weixin.store import load_reply, save_reply
    with database() as db:
        db.execute("INSERT INTO channel_messages(provider,account_id,message_id,status) VALUES('weixin_ilink','bot','cached','processing')")
        assert save_reply(db, "bot", "cached", "frozen answer") == "frozen answer"
    with database() as db:
        assert load_reply(db, "bot", "cached") == "frozen answer"
        assert load_reply(db, "other-bot", "cached") is None
        assert save_reply(db, "bot", "cached", "new answer") == "frozen answer"


def test_replayed_sync_reuses_completed_original_job_after_cooldown(database):
    connect = database
    job, target = submit(connect)
    complete(connect, job)
    with connect() as db:
        db.execute("UPDATE academic_sync_jobs SET created_at=CURRENT_TIMESTAMP-INTERVAL '1 hour'")
    replayed = academic_jobs.enqueue(7, job["term"], True, cooldown_seconds=30, notification_target=target)
    assert replayed["id"] == job["id"]
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM academic_sync_jobs").fetchone()["n"] == 1


def test_reply_migration_can_upgrade_repeatedly(database, monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0021_message_reply.py"
    spec = importlib.util.spec_from_file_location("message_reply_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with database() as db:
        monkeypatch.setattr(migration.op, "execute", db.execute)
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
        assert db.execute("SELECT reply_text FROM channel_messages LIMIT 1").fetchone() is None


def test_notification_reassignment_does_not_destroy_original_message_idempotency(database):
    connect = database
    target = {"provider":"weixin_ilink", "sender_id":"sender", "account_id":"bot", "message_id":"m1"}
    first = academic_jobs.enqueue(7, "2026-2027-1", True, cooldown_seconds=30, notification_target=target)
    second = academic_jobs.enqueue(7, "2026-2027-1", True, cooldown_seconds=30,
                                   notification_target=dict(target, message_id="m2"))
    assert first["id"] == second["id"]
    with connect() as db:
        assert db.execute("SELECT message_id FROM academic_sync_notifications").fetchone()["message_id"] == "m2"
        db.execute("UPDATE academic_sync_jobs SET state='succeeded',created_at=CURRENT_TIMESTAMP-INTERVAL '1 hour'")
    replayed = academic_jobs.enqueue(7, "2026-2027-1", True, cooldown_seconds=30, notification_target=target)
    assert replayed["id"] == first["id"]
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM academic_sync_jobs").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) AS n FROM academic_sync_requests").fetchone()["n"] == 2


def test_replayed_message_cannot_start_sync_for_changed_binding(database):
    from fastapi import HTTPException
    connect = database
    job, target = submit(connect)
    with connect() as db:
        db.execute("UPDATE academic_sync_jobs SET state='succeeded'")
        db.execute("UPDATE academic_bindings SET revision=4")
    with pytest.raises(HTTPException) as error:
        academic_jobs.enqueue(7, job["term"], True, notification_target=target)
    assert error.value.status_code == 409
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM academic_sync_jobs").fetchone()["n"] == 1


def test_idempotency_record_rolls_back_with_subscription_failure(database, monkeypatch):
    connect = database
    def fail(*args):
        raise RuntimeError("subscription failed")
    monkeypatch.setattr(notifications, "subscribe", fail)
    target = {"provider":"weixin_ilink", "sender_id":"sender", "account_id":"bot", "message_id":"m1"}
    with pytest.raises(RuntimeError):
        academic_jobs.enqueue(7, "2026-2027-1", True, notification_target=target)
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM academic_sync_jobs").fetchone()["n"] == 0
        assert db.execute("SELECT count(*) AS n FROM academic_sync_requests").fetchone()["n"] == 0


def test_request_migration_backfills_once_and_preserves_original_mapping(database, monkeypatch):
    import importlib.util
    from pathlib import Path
    connect = database
    job, _ = submit(connect)
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0022_sync_request_ids.py"
    spec = importlib.util.spec_from_file_location("sync_request_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with connect() as db:
        monkeypatch.setattr(migration.op, "execute", db.execute)
        migration.downgrade()
        migration.upgrade()
        assert db.execute("SELECT job_id FROM academic_sync_requests WHERE message_id='m1'").fetchone()["job_id"] == job["id"]
        db.execute("UPDATE academic_sync_notifications SET message_id='m2'")
        migration.upgrade()
        assert db.execute("SELECT job_id FROM academic_sync_requests WHERE message_id='m1'").fetchone()["job_id"] == job["id"]
        assert db.execute("SELECT count(*) AS n FROM academic_sync_requests").fetchone()["n"] == 2
