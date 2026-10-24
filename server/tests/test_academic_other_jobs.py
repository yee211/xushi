"""Persistent batch queue tests using isolated PostgreSQL and mocked school IO."""
# ruff: noqa: F811 -- pytest fixtures are imported for reuse
import os
import uuid

import pytest
from fastapi import HTTPException

from app.services import academic_other_jobs as jobs
from app.services import academic_others as others
from tests.test_academic_others_db import database  # noqa: F401

pytestmark = pytest.mark.skipif(os.getenv("TEST_ACADEMIC_DIRECTORY_DB") != "1", reason="Requires PostgreSQL")


@pytest.fixture
def queue(database, monkeypatch):
    monkeypatch.setattr(jobs, "connect", database)
    with database() as db:
        for statement in jobs.SCHEMA:
            db.execute(statement)
    return database


def ready(queue):
    with queue() as db:
        db.execute("UPDATE academic_other_sync_jobs SET available_at=CURRENT_TIMESTAMP-INTERVAL '1 second'")


def test_batch_deduplicates_and_enforces_ownership(queue):
    others.save(1, "student-a", "2026-2027-1", "室友")
    job = jobs.enqueue(1)
    assert jobs.enqueue(1)["id"] == job["id"]
    assert job["total"] == 1 and job["done"] == 0
    assert job["items"][0]["term"] == "2026-2027-1"
    with pytest.raises(HTTPException) as caught:
        jobs.read(2, job["id"])
    assert caught.value.status_code == 404
    assert jobs.read(2) is None


def test_batch_partial_failure_preserves_old_data_and_retry_only_failed(queue, monkeypatch):
    others.save(1, "student-a", "2026-2027-1", "室友")
    others.save(1, "student-b", "2025-2026-2", "搭子")
    job = jobs.enqueue(1)
    calls = []
    def fetch(sid, term, refresh=False):
        calls.append((sid, term))
        if sid == "student-b":
            raise others.academic.AcademicError("upstream_timeout", "学校超时", 504)
        return {"complete": True, "courses": [{"name": "新课"}]}
    monkeypatch.setattr(others.academic, "get_schedule", fetch)
    assert jobs.process_one()
    assert jobs.read(1, job["id"])["done"] == 1
    ready(queue)
    assert jobs.process_one()
    result = jobs.read(1, job["id"])
    assert (result["state"], result["updated"], result["failed"], result["skipped"]) == ("completed", 1, 1, 0)
    people = {p["student_id"]: p for p in others.list_saved(1)["people"]}
    assert people["student-a"]["remark"] == "室友"
    assert people["student-b"]["snapshot"]["courses"] == []
    assert calls == [("student-a", "2026-2027-1"), ("student-b", "2025-2026-2")]
    retry = jobs.enqueue(1, retry_of=job["id"])
    assert [i["student_id"] for i in retry["items"]] == ["student-b"]


@pytest.mark.parametrize("change", ["delete", "term", "remark"])
def test_batch_skips_changed_people_before_network(queue, monkeypatch, change):
    others.save(1, "student-a", "2026-2027-1", "室友")
    jobs.enqueue(1)
    with queue() as db:
        if change == "delete":
            db.execute("DELETE FROM academic_others WHERE user_id=1")
        elif change == "term":
            db.execute("UPDATE academic_others SET term='2026-2027-2',updated_at=clock_timestamp() WHERE user_id=1")
        else:
            db.execute("UPDATE academic_others SET remark='新备注',updated_at=clock_timestamp() WHERE user_id=1")
    monkeypatch.setattr(others.academic, "get_schedule", lambda *args: pytest.fail("Changed favorite must be skipped before network"))
    assert jobs.process_one()
    result = jobs.read(1)
    assert result["state"] == "completed" and result["skipped"] == 1
    assert result["failed"] == 0
    if change == "delete":
        assert not others.list_saved(1)["people"]


def test_rate_limit_defers_without_failing_person(queue, monkeypatch):
    others.save(1, "student-a", "2026-2027-1")
    jobs.enqueue(1)
    monkeypatch.setattr(others.query_limiter, "hit", lambda key: (False, 10))
    assert jobs.process_one()
    result = jobs.read(1)
    assert result["state"] == "running" and result["done"] == result["failed"] == 0
    assert not jobs.process_one()
    monkeypatch.setattr(others.query_limiter, "hit", lambda key: (True, 0))
    ready(queue)
    assert jobs.process_one()
    assert jobs.read(1)["updated"] == 1


def test_expired_worker_lease_recovers_after_process_restart(queue, monkeypatch):
    others.save(1, "student-a", "2026-2027-1")
    jobs.enqueue(1)
    original = others.academic.get_schedule
    def terminate(*args):
        raise SystemExit("simulated worker exit")
    monkeypatch.setattr(others.academic, "get_schedule", terminate)
    with pytest.raises(SystemExit):
        jobs.process_one()
    assert jobs.read(1)["state"] == "running"
    assert not jobs.process_one()  # Another worker cannot steal an active lease.
    with queue() as db:
        db.execute("UPDATE academic_other_sync_jobs SET leased_until=CURRENT_TIMESTAMP-INTERVAL '1 second'")
    monkeypatch.setattr(others.academic, "get_schedule", original)
    assert jobs.process_one()
    assert jobs.read(1)["state"] == "completed"


def test_queue_continues_for_another_user_during_spacing_delay(queue):
    others.save(1, "student-a", "2026-2027-1")
    others.save(1, "student-b", "2026-2027-1")
    others.save(2, "student-c", "2026-2027-1")
    jobs.enqueue(1)
    jobs.enqueue(2)
    assert jobs.process_one()
    assert jobs.process_one()
    assert jobs.read(1)["done"] == 1
    assert jobs.read(2)["state"] == "completed"


def test_no_favorites_or_foreign_retry_cannot_create_batch(queue):
    with pytest.raises(HTTPException) as caught:
        jobs.enqueue(1)
    assert caught.value.status_code == 409
    others.save(2, "student-a", "2026-2027-1")
    foreign = jobs.enqueue(2)
    with pytest.raises(HTTPException) as caught:
        jobs.enqueue(1, retry_of=foreign["id"])
    assert caught.value.status_code == 404


def test_stale_active_batch_is_expired_and_replaced(queue):
    others.save(1, "student-a", "2026-2027-1", "室友")
    old = jobs.enqueue(1)
    with queue() as db:
        db.execute("""UPDATE academic_other_sync_jobs SET updated_at=CURRENT_TIMESTAMP-INTERVAL '20 minutes'
            WHERE id=%s""", (old["id"],))
    expired = jobs.read(1)
    assert expired["state"] == "failed" and expired["failed"] == 1
    fresh = jobs.enqueue(1)
    assert fresh["id"] != old["id"] and fresh["state"] == "queued"


def test_live_running_batch_is_not_expired(queue):
    others.save(1, "student-a", "2026-2027-1")
    job = jobs.enqueue(1)
    with queue() as db:
        db.execute("""UPDATE academic_other_sync_jobs SET state='running',lease_token=%s,
            leased_until=CURRENT_TIMESTAMP+INTERVAL '60 seconds',
            updated_at=CURRENT_TIMESTAMP-INTERVAL '20 minutes' WHERE id=%s""", (uuid.uuid4(), job["id"]))
    assert jobs.read(1)["state"] == "running"
    assert jobs.enqueue(1)["id"] == job["id"]


def test_job_without_pending_items_closes_instead_of_looping(queue):
    others.save(1, "student-a", "2026-2027-1")
    job = jobs.enqueue(1)
    with queue() as db:
        db.execute("""UPDATE academic_other_sync_jobs SET state='running',
            items=jsonb_set(items,'{0,state}','"updated"') WHERE id=%s""", (job["id"],))
    ready(queue)
    assert jobs.process_one()
    assert jobs.read(1)["state"] == "completed"


def test_single_refresh_scope_and_active_conflict(queue):
    others.save(1, "student-a", "2026-2027-1", "室友")
    others.save(1, "student-b", "2026-2027-1", "搭子")
    job = jobs.enqueue(1, student_ids=["student-a"])
    assert [item["student_id"] for item in job["items"]] == ["student-a"]
    assert jobs.enqueue(1, student_ids=["student-a"])["id"] == job["id"]
    for ids in (None, ["student-b"]):
        with pytest.raises(HTTPException) as caught:
            jobs.enqueue(1, student_ids=ids)
        assert caught.value.status_code == 409
