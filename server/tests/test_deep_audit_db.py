"""Deep audit regressions using real PostgreSQL in disposable schemas."""
# ruff: noqa: F811 -- imported pytest fixture reused below
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app.auth import deps
from app.auth.jwt import create_token
from app.routers import adjustments, admin, courses
from app.schemas import CourseAdjustmentIn
from tests.test_schedule_backups import database  # noqa: F401

pytestmark = pytest.mark.skipif(os.getenv("TEST_ACADEMIC_QUEUE_DB") != "1", reason="Requires PostgreSQL")


def test_only_latest_adjustment_record_can_remove_live_change(database, monkeypatch):
    connect, user, schedule, course = database
    monkeypatch.setattr(adjustments, "connect", connect)
    with connect() as db:
        ids = []
        for target in [3, 5]:
            details = json.dumps([{"course_id": course, "week": 1, "new_start_section": target}])
            ids.append(db.execute("""INSERT INTO course_change_logs(schedule_id,course_id,action_type,title,details)
                VALUES(%s,%s,'drag_move','test',%s::jsonb) RETURNING id""", (schedule, course, details)).fetchone()["id"])
    records = adjustments.list_records(schedule, {"id": user})
    by_id = {row["id"]: row for row in records}
    assert not by_id[ids[0]]["can_revoke"]
    assert by_id[ids[1]]["can_revoke"]
    with pytest.raises(HTTPException) as error:
        adjustments.delete_record(ids[1], {"id": user})
    assert error.value.status_code == 409
    assert adjustments.revoke_adjustment_record(ids[0], {"id": user})["revoked"] == 0
    assert adjustments.revoke_adjustment_record(ids[1], {"id": user})["revoked"] == 1
    adjustments.delete_record(ids[1], {"id": user})


def test_admin_revokes_database_sessions_and_old_jwts(database, monkeypatch):
    connect, user, _, _ = database
    monkeypatch.setattr(admin, "connect", connect)
    monkeypatch.setattr(deps, "connect", connect)
    token = create_token(user, "test")
    opaque = "opaque-audit-session"
    with connect() as db:
        db.execute("INSERT INTO sessions VALUES(%s,%s,CURRENT_TIMESTAMP+INTERVAL '1 day',CURRENT_TIMESTAMP)", (deps.token_hash(opaque), user))
    assert deps._user_from_jwt(token)["id"] == user
    assert deps._user_from_session(opaque)["id"] == user
    admin.clear_user_sessions(admin.ClearSessionIn(user_id=user), "root")
    assert deps._user_from_session(opaque) is None
    with pytest.raises(HTTPException):
        deps._user_from_jwt(token)
    assert deps._user_from_jwt(create_token(user, "test"))["id"] == user


def test_concurrent_adjustment_retries_return_idempotent_result(database, monkeypatch):
    connect, user, _, course = database
    monkeypatch.setattr(courses, "connect", connect)
    payload = CourseAdjustmentIn(week=1, weekday=4, start_section=5, end_section=6, room="A101")
    def submit(_):
        return courses.upsert_adjustment(course, 1, payload, idempotency_key="same-retry", user={"id": user})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sum(bool(row.get("duplicate")) for row in results) == 1


def test_unlink_copies_jsonb_weeks_and_single_week_adjustments(database):
    from app.services.account_link import unlink_wechat
    connect, user, schedule, course = database
    with connect() as db:
        db.execute("UPDATE users SET openid='audit-unlink-openid' WHERE id=%s", (user,))
        result = unlink_wechat(db, user)
    with connect() as db:
        copied = db.execute("""SELECT c.* FROM courses c JOIN schedules s ON s.id=c.schedule_id
            WHERE s.user_id=%s AND s.name='old'""", (result["wx_user_id"],)).fetchone()
        assert copied["weeks"] == [1, 2]
        adjustment = db.execute("SELECT * FROM course_adjustments WHERE course_id=%s", (copied["id"],)).fetchone()
        assert (adjustment["week"], adjustment["weekday"], adjustment["start_section"]) == (1, 2, 3)
        assert db.execute("SELECT openid FROM users WHERE id=%s", (user,)).fetchone()["openid"] is None
        assert db.execute("SELECT weeks FROM courses WHERE id=%s", (course,)).fetchone()["weeks"] == [1, 2]


def test_poison_message_is_quarantined_without_blocking_later_messages(database, monkeypatch, caplog):
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from app.channels.weixin import store, worker
    from app.channels.weixin.protocol import InboundText

    connect, _, _, _ = database
    monkeypatch.setattr(worker, "connect", connect)
    monkeypatch.setattr(worker.clawbot_limiter, "hit", lambda _: (True, 0))
    agent = MagicMock(side_effect=RuntimeError("poison"))
    monkeypatch.setattr(worker, "build_agent_reply", agent)
    client = MagicMock()
    poison = InboundText("test-bot", "sender", "poison", "poison text", "context", datetime.now(UTC))
    for expected in (False, False, True):
        assert worker.process_message(client, poison) is expected
    assert worker.process_message(client, poison) is True
    assert agent.call_count == 3
    assert "quarantined" in caplog.text
    with connect() as db:
        dead = db.execute("SELECT * FROM channel_message_dead_letters WHERE message_id='poison'").fetchone()
        assert dead["payload"]["text"] == "poison text" and dead["attempts"] == 3
        assert store.message_completed(db, "test-bot", "poison")
    agent.side_effect = None
    agent.return_value = "recovered"
    later = InboundText("test-bot", "sender", "later", "next message", "context", datetime.now(UTC))
    assert worker.process_message(client, later) is True
    with connect() as db:
        replay = store.prepare_replay(db, "test-bot", "poison")
    assert worker.process_message(client, replay) is True
    with connect() as db:
        dead = db.execute("SELECT resolved_at FROM channel_message_dead_letters WHERE message_id='poison'").fetchone()
        assert dead["resolved_at"] is not None
        assert db.execute("SELECT status FROM channel_messages WHERE message_id='later'").fetchone()["status"] == "done"


def _quarantine_direct(connect, message):
    from app.channels.weixin import store
    with connect() as db:
        db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status,attempts,error)
            VALUES('weixin_ilink',%s,%s,'failed',3,'boom')""", (message.account_id, message.message_id))
        assert store.quarantine_message(db, message)
        assert db.execute("SELECT status FROM channel_messages WHERE message_id=%s",
                          (message.message_id,)).fetchone()["status"] == "dead_letter"


def test_failed_replay_script_restores_dead_letter_for_retry(database, monkeypatch):
    import importlib.util
    import sys
    from datetime import UTC, datetime
    from pathlib import Path
    from unittest.mock import MagicMock

    from app.channels.weixin.protocol import Credentials, InboundText

    connect, _, _, _ = database
    message = InboundText("test-bot", "sender", "replay-fail", "poison text", "context", datetime.now(UTC))
    _quarantine_direct(connect, message)

    spec = importlib.util.spec_from_file_location(
        "replay_weixin_message", Path(__file__).resolve().parents[1] / "scripts" / "replay_weixin_message.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "connect", connect)
    monkeypatch.setattr(module, "load_accounts",
                        lambda db: [(Credentials("test-bot", "token", "https://example.invalid", ""), "", "fp")])
    monkeypatch.setattr(module, "process_message", lambda client, message: False)
    monkeypatch.setattr(module, "ILinkClient", MagicMock())
    monkeypatch.setattr(sys, "argv", ["replay", "--account", "test-bot", "--message", "replay-fail"])

    with pytest.raises(SystemExit, match="restored"):
        module.main()
    with connect() as db:
        assert db.execute("SELECT status FROM channel_messages WHERE message_id='replay-fail'").fetchone()["status"] == "dead_letter"
        assert db.execute("SELECT resolved_at FROM channel_message_dead_letters WHERE message_id='replay-fail'"
                          ).fetchone()["resolved_at"] is None
        # 恢复死信态后可立即再次重放
        from app.channels.weixin import store
        assert store.prepare_replay(db, "test-bot", "replay-fail").message_id == "replay-fail"


def test_crashed_replay_leaves_failed_message_still_replayable(database):
    from datetime import UTC, datetime

    from app.channels.weixin import store
    from app.channels.weixin.protocol import InboundText

    connect, _, _, _ = database
    _quarantine_direct(connect, InboundText("test-bot", "sender", "replay-crash", "text", "ctx", datetime.now(UTC)))
    with connect() as db:
        first = store.prepare_replay(db, "test-bot", "replay-crash")
        assert db.execute("SELECT status FROM channel_messages WHERE message_id='replay-crash'").fetchone()["status"] == "failed"
        # 模拟脚本在恢复前崩溃：failed 状态直接悬置，再次 prepare 仍可领取
        second = store.prepare_replay(db, "test-bot", "replay-crash")
    assert first.message_id == second.message_id == "replay-crash"


def test_sync_notification_claim_accepts_dead_letter_source(database):
    import uuid

    from app.services import academic_sync_notifications as notifications

    connect, user, _, _ = database
    job_id = uuid.uuid4()
    with connect() as db:
        db.execute("""INSERT INTO academic_sync_jobs(id,user_id,student_id,binding_revision,binding_updated_at,term,state)
            VALUES(%s,%s,'student',1,CURRENT_TIMESTAMP,'2026-2027-1','succeeded')""", (job_id, user))
        db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status,attempts)
            VALUES('weixin_ilink','test-bot','sync-ask','dead_letter',3)""")
        db.execute("""INSERT INTO academic_sync_notifications(id,job_id,user_id,provider,sender_id,account_id,message_id)
            VALUES(%s,%s,%s,'weixin_ilink','sender','test-bot','sync-ask')""", (uuid.uuid4(), job_id, user))
    with connect() as db:
        claimed = notifications.claim(db)
    assert claimed is not None
    row, job = claimed
    assert row["message_id"] == "sync-ask" and row["state"] == "sending"
    assert job["state"] == "succeeded"


def test_startup_cleanup_purges_resolved_dead_letters_but_keeps_pending(database):
    from app.db import schema as db_schema

    connect, _, _, _ = database
    with connect() as db:
        db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status,attempts,processed_at)
            VALUES('weixin_ilink','test-bot','old-done','done',1,CURRENT_TIMESTAMP-INTERVAL '40 days')""")
        db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status,attempts,error,processed_at)
            VALUES('weixin_ilink','test-bot','old-failed','failed',2,'gone',CURRENT_TIMESTAMP-INTERVAL '100 days')""")
        db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status,attempts,processed_at)
            VALUES('weixin_ilink','test-bot','kept-dead','dead_letter',3,CURRENT_TIMESTAMP-INTERVAL '100 days')""")
        db.execute("INSERT INTO channel_message_dead_letters(provider,account_id,message_id,payload,error,attempts,resolved_at)"
                   " VALUES('weixin_ilink','test-bot','old-done','{}'::jsonb,'x',3,CURRENT_TIMESTAMP-INTERVAL '40 days')")
        db.execute("INSERT INTO channel_message_dead_letters(provider,account_id,message_id,payload,error,attempts)"
                   " VALUES('weixin_ilink','test-bot','kept-dead','{}'::jsonb,'x',3)")
    db_schema.init_db()
    with connect() as db:
        statuses = {row["message_id"]: row["status"] for row in db.execute(
            "SELECT message_id,status FROM channel_messages WHERE message_id LIKE '%done%' OR message_id LIKE '%failed%' OR message_id LIKE '%dead%'").fetchall()}
        dead = db.execute("SELECT message_id FROM channel_message_dead_letters").fetchall()
    assert statuses == {"kept-dead": "dead_letter"}
    assert [row["message_id"] for row in dead] == ["kept-dead"]
