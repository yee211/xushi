"""One backend contract for Android JWT and miniapp session users."""
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import create_token, deps
from app.routers import academic as routes
from app.services import academic
from app.services import academic_binding as service

STUDENT = {"id": "student123", "name": "同学", "default_term": "2026-2027-1"}
SNAPSHOT = {"complete": True, "stale": False, "start_date": "2026-09-01", "end_date": "2027-01-20",
            "courses": [{"name": "高数", "weekday": 1, "start_section": 1, "end_section": 2, "weeks": [1]}]}


class Result:
    def __init__(self, row=None):
        self.row = row
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.row or []


class Db:
    def __init__(self):
        self.bindings, self.schedules, self.calls, self.writes = {}, {}, [], []
        self.next_id = 100
    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        if "pg_advisory_xact_lock" in sql:
            return Result()
        if sql.startswith("SELECT student"):
            return Result(self.bindings.get(params[0]))
        if sql.startswith("INSERT INTO academic_bindings"):
            import json
            old = self.bindings.get(params[0], {})
            row = {"student": json.loads(params[1]), "revision": old.get("revision", 0)+1,
                   "updated_at": datetime.now(UTC), "last_synced_at": None, "last_synced_term": None}
            self.bindings[params[0]] = row
            return Result(row)
        if sql.startswith("DELETE FROM academic_bindings"):
            self.bindings.pop(params[0], None)
            return Result()
        if sql.startswith("SELECT id,name,term"):
            rows = [(key, row) for key, row in self.schedules.items() if key[0] == params[0]]
            return Result(max(rows, key=lambda item: (item[0][1] == params[1], item[1]["id"]))[1] if rows else None)
        if sql.startswith("SELECT * FROM courses"):
            rows = [row for row in self.schedules.values() if row["id"] == params[0]]
            return Result(rows[0]["courses"] if rows else [])
        if sql.startswith("SELECT 1 FROM schedules"):
            return Result(next((row for key, row in self.schedules.items() if key[0] == params[0] and row["id"] != params[1]), None))
        if sql.startswith("DELETE FROM schedules WHERE user_id"):
            self.schedules = {key: row for key, row in self.schedules.items() if key[0] != params[0] or row["id"] == params[1]}
            return Result()
        if sql.startswith("UPDATE schedules SET academic_student_id"):
            for row in self.schedules.values():
                if row["id"] == params[2]:
                    row["academic_snapshot_hash"] = params[1]
            return Result()
        if sql.startswith("UPDATE academic_bindings SET last_synced_at"):
            row = self.bindings[params[1]]
            row.update(last_synced_at=datetime.now(UTC), last_synced_term=params[0])
            return Result(row)
        if sql.startswith("SELECT id FROM schedules WHERE source_schedule_id"):
            return Result()
        raise AssertionError(sql)
    def write(self, db, **kwargs):
        self.writes.append(kwargs)
        sid = kwargs.get("target_schedule_id") or self.next_id
        self.next_id += 1
        row = {"id": sid, "name": kwargs["parsed"]["name"], "term": kwargs["parsed"]["term"], "academic_snapshot_hash": None, "start_date": kwargs["start_date"], "end_date": kwargs["end_date"], "courses": kwargs["parsed"]["courses"]}
        self.schedules = {key: old for key, old in self.schedules.items() if old["id"] != sid}
        self.schedules[(kwargs["user_id"], STUDENT["id"], row["term"])] = row
        return {"schedule_id": sid, "imported": len(kwargs["parsed"]["courses"]), "name": row["name"], "term": row["term"]}


@pytest.fixture
def db(monkeypatch):
    db = Db()
    @contextmanager
    def connect():
        yield db
    monkeypatch.setattr(service, "connect", connect)
    monkeypatch.setattr(service, "write_schedule", db.write)
    db.backups = []
    def capture(connection, user_id):
        from copy import deepcopy
        db.backups.append(deepcopy([row for key, row in db.schedules.items() if key[0] == user_id]))
    monkeypatch.setattr(service.schedule_backups, "capture", capture)
    monkeypatch.setattr(academic, "student_context", lambda sid: dict(STUDENT, id=sid))
    monkeypatch.setattr(academic, "get_schedule", lambda *args: dict(SNAPSHOT))
    return db


def test_android_and_miniapp_share_binding_and_sync_contract(db, monkeypatch):
    monkeypatch.setattr(deps, "_user_from_session", lambda token: {"id": 5 if token == "wx-shared" else 6})
    app = FastAPI()
    app.include_router(routes.router)
    android = {"Authorization": "Bearer " + create_token(5, "android")}
    miniapp = {"Authorization": "Bearer wx-shared"}
    other = {"Authorization": "Bearer wx-other"}
    with TestClient(app) as client:
        assert client.put("/api/academic/binding", headers=android, json={"student_id": STUDENT["id"]}).status_code == 200
        assert client.get("/api/academic/binding", headers=miniapp).json()["student"] == STUDENT
        assert client.get("/api/academic/binding", headers=other).json() == {"student": None}
        first = service.sync(5, "2026-2027-1")
        second = service.sync(5, "2026-2027-1")
        assert first["schedule_id"] == second["schedule_id"]
        assert second["unchanged"] and len(db.writes) == 1
        assert client.get("/api/academic/binding", headers=android).json()["last_synced_at"]
        assert client.delete("/api/academic/binding", headers=miniapp).status_code == 200
        assert client.get("/api/academic/binding", headers=android).json() == {"student": None}


@pytest.mark.parametrize("change", ["revision", "updated_at", "unbind"])
def test_inflight_sync_cannot_write_after_binding_changes(db, monkeypatch, change):
    service.bind(5, STUDENT["id"])
    def fetch(*args):
        if change == "revision":
            db.bindings[5] = dict(db.bindings[5], revision=2)
        elif change == "updated_at":
            db.bindings[5] = dict(db.bindings[5], updated_at=datetime.now(UTC))
        else:
            db.bindings.pop(5)
        return dict(SNAPSHOT)
    monkeypatch.setattr(academic, "get_schedule", fetch)
    with pytest.raises(HTTPException) as error:
        service.sync(5, "2026-2027-1")
    assert error.value.status_code == 409 and not db.writes


def test_changed_snapshot_updates_the_same_school_schedule(db, monkeypatch):
    service.bind(5, STUDENT["id"])
    first = service.sync(5, "2026-2027-1")
    changed = dict(SNAPSHOT, courses=[dict(SNAPSHOT["courses"][0], room="new-room")])
    monkeypatch.setattr(academic, "get_schedule", lambda *args: changed)
    second = service.sync(5, "2026-2027-1")
    assert second["schedule_id"] == first["schedule_id"]
    assert not second["unchanged"]
    assert not db.writes[-1]["preserve_adjusted"]


def test_sync_leaves_one_schedule_per_account_and_does_not_touch_other_users(db):
    service.bind(5, STUDENT["id"])
    db.schedules[(6, "other", "old")] = {"id": 99}
    first = service.sync(5, "2026-2027-1")
    db.schedules[(5, "manual", "old")] = {"id": 98, "name": "导入课表", "term": "old", "academic_snapshot_hash": None}
    second = service.sync(5, "2026-2027-2")
    assert len([key for key in db.schedules if key[0] == 5]) == 1
    assert (6, "other", "old") in db.schedules
    assert second["schedule_id"] == first["schedule_id"]
    assert second["overwrite_policy"] == "single_school_schedule"
    assert db.calls[-1][1] == (5, second["schedule_id"])


def test_sync_restores_personal_edits_even_when_school_snapshot_is_unchanged(db):
    service.bind(5, STUDENT["id"])
    first = service.sync(5, "2026-2027-1")
    row = next(iter(db.schedules.values()))
    row["courses"] = [dict(SNAPSHOT["courses"][0], room="personal-edit")]
    second = service.sync(5, "2026-2027-1")
    assert second["schedule_id"] == first["schedule_id"]
    assert not second["unchanged"] and len(db.writes) == 2
    assert db.backups[-1][0]["courses"][0]["room"] == "personal-edit"


@pytest.mark.parametrize("flags", [{"complete": False}, {"stale": True}])
def test_failed_school_fetch_preserves_existing_schedule(db, monkeypatch, flags):
    service.bind(5, STUDENT["id"])
    first = service.sync(5, "2026-2027-1")
    before = dict(db.schedules)
    writes = len(db.writes)
    monkeypatch.setattr(academic, "get_schedule", lambda *args: dict(SNAPSHOT, **flags))
    with pytest.raises(HTTPException):
        service.sync(5, "2026-2027-1")
    assert db.schedules == before and len(db.writes) == writes
    assert next(iter(db.schedules.values()))["id"] == first["schedule_id"]


def test_verified_empty_semester_replaces_old_courses(db, monkeypatch):
    service.bind(5, STUDENT["id"])
    first = service.sync(5, "2026-2027-1")
    monkeypatch.setattr(academic, "get_schedule", lambda *args: dict(SNAPSHOT, courses=[]))
    second = service.sync(5, "2026-2027-2")
    assert second["schedule_id"] == first["schedule_id"]
    assert second["imported"] == 0 and not second["unchanged"]
    assert db.writes[-1]["allow_empty"]
    assert db.backups[-1][0]["courses"] == SNAPSHOT["courses"]
    assert next(iter(db.schedules.values()))["courses"] == []



def test_cached_snapshot_refresh_failure_remains_retryable_without_overwrite(db, monkeypatch):
    service.bind(5, STUDENT["id"])
    service.sync(5, "2026-2027-1")
    writes = len(db.writes)
    monkeypatch.setattr(academic, "get_schedule", lambda *args: dict(SNAPSHOT, stale=True,
        refresh_error={"code": "upstream_failed", "message": "学校连接暂不可用"}))
    with pytest.raises(academic.AcademicError) as error:
        service.sync(5, "2026-2027-1", True)
    assert error.value.status == 502 and len(db.writes) == writes
