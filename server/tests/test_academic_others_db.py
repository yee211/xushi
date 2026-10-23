"""Real PostgreSQL coverage in an isolated schema; no school/network requests."""
import importlib.util
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import connect as real_connect
from app.services import academic_others as service
from app.services.account_link import _move_other_schedules

pytestmark = pytest.mark.skipif(os.getenv("TEST_ACADEMIC_DIRECTORY_DB") != "1", reason="Requires PostgreSQL")


@pytest.fixture
def database(monkeypatch):
    schema = "test_others_" + uuid.uuid4().hex
    with real_connect() as db:
        db.execute("CREATE SCHEMA " + schema)
    @contextmanager
    def isolated():
        with real_connect() as db:
            db.execute("SELECT set_config('search_path',%s,false)", (schema,))
            db.commit()
            try:
                yield db
                db.commit()
            finally:
                db.rollback()
                db.execute("RESET search_path")
                db.commit()
    try:
        with isolated() as db:
            db.execute("CREATE TABLE users(id BIGINT PRIMARY KEY)")
            db.execute("INSERT INTO users VALUES (1),(2)")
            path = Path(__file__).parents[1] / "migrations/versions/0023_academic_others.py"
            spec = importlib.util.spec_from_file_location("others_migration_test", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            migration.op = SimpleNamespace(execute=db.execute)
            migration.upgrade()
        monkeypatch.setattr(service, "connect", isolated)
        monkeypatch.setattr(service.query_limiter, "hit", lambda key: (True, 0))
        monkeypatch.setattr(service.academic, "get_schedule", lambda *args: {"complete": True, "courses": []})
        yield isolated
    finally:
        with real_connect() as db:
            db.execute("DROP SCHEMA " + schema + " CASCADE")


def test_real_save_preserves_or_clears_remarks(database):
    service.save(1, "student-a", "2026-2027-1", "室友")
    service.save(1, "student-a", "2026-2027-1")
    assert service.list_saved(1)["people"][0]["remark"] == "室友"
    service.save(1, "student-a", "2026-2027-1", "")
    assert service.list_saved(1)["people"][0]["remark"] == ""


@pytest.mark.parametrize("operation", ["delete", "edit"])
def test_real_refresh_compare_and_swap(database, monkeypatch, operation):
    service.save(1, "student-a", "2026-2027-1", "室友")
    def upstream(*args):
        with database() as db:
            if operation == "delete":
                db.execute("DELETE FROM academic_others WHERE user_id=1")
            else:
                db.execute("UPDATE academic_others SET remark='新备注', updated_at=clock_timestamp() WHERE user_id=1")
        return {"complete": True, "courses": [{"name": "新课"}]}
    monkeypatch.setattr(service.academic, "get_schedule", upstream)
    with pytest.raises(service.academic.AcademicError) as caught:
        service.refresh_saved(1, "student-a")
    assert caught.value.code == "saved_person_changed"
    people = service.list_saved(1)["people"]
    assert not people if operation == "delete" else people[0]["remark"] == "新备注" and people[0]["snapshot"]["courses"] == []


def test_real_transfer_newer_wins_and_deletions_do_not_resurrect(database):
    service.save(1, "bob", "2026-2027-1", "旧备注")
    service.save(1, "carol", "2026-2027-1", "同学")
    service.save(2, "bob", "2026-2027-1", "新备注")
    with database() as db:
        _move_other_schedules(db, 2, 1)
    assert next(p for p in service.list_saved(1)["people"] if p["student_id"] == "bob")["remark"] == "新备注"
    with database() as db:
        _move_other_schedules(db, 1, 2)
    assert service.list_saved(1)["people"] == []
    service.remove(2, "carol")
    service.save(2, "bob", "2026-2027-1", "解绑期间更新")
    with database() as db:
        _move_other_schedules(db, 2, 1)
    rows = service.list_saved(1)["people"]
    assert len(rows) == 1 and rows[0]["student_id"] == "bob" and rows[0]["remark"] == "解绑期间更新"


def test_real_favorites_limit_allows_existing_update(database, monkeypatch):
    monkeypatch.setattr(service, "MAX_SAVED_PEOPLE", 1)
    service.save(1, "student-a", "2026-2027-1")
    with pytest.raises(service.academic.AcademicError):
        service.save(1, "student-b", "2026-2027-1")
    service.save(1, "student-a", "2026-2027-1", "可更新")
    assert service.list_saved(1)["people"][0]["remark"] == "可更新"
