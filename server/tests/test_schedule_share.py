"""课表分享码与口令导入单元测试。"""
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.services import schedule_share
from app.services.schedule_share import ShareError
from fakes import FakeResult


class FakeShareDb:
    def __init__(self, schedules=None, courses=None, share_codes=None, users=None):
        self.schedules = schedules or {}  # id -> dict
        self.courses = courses or {}  # schedule_id -> list of dicts
        self.share_codes = share_codes or {}  # code -> dict
        self.users = users or {1: {"id": 1, "username": "alice", "email": "alice@test.com"},
                                2: {"id": 2, "username": "bob", "email": "bob@test.com"}}
        self.calls = []
        self._next_schedule_id = 100
        self._next_share_id = 10

    def execute(self, sql, params=None):
        cleaned = " ".join(sql.split())
        self.calls.append((cleaned, params))

        if cleaned.startswith("SELECT id, name, term FROM schedules WHERE id=%s AND user_id=%s"):
            sched_id, user_id = params
            sched = self.schedules.get(sched_id)
            if sched and sched.get("user_id") == user_id:
                return FakeResult([sched])
            return FakeResult([])

        if "SELECT code, expires_at FROM schedule_share_codes WHERE schedule_id=%s AND user_id=%s" in cleaned:
            sched_id, user_id = params
            for item in self.share_codes.values():
                if item["schedule_id"] == sched_id and item["user_id"] == user_id and item["expires_at"] > datetime.now(UTC):
                    return FakeResult([item])
            return FakeResult([])

        if cleaned.startswith("INSERT INTO schedule_share_codes"):
            code, schedule_id, user_id, expires_at = params
            self.share_codes[code] = {
                "id": self._next_share_id,
                "code": code,
                "schedule_id": schedule_id,
                "user_id": user_id,
                "expires_at": expires_at,
            }
            self._next_share_id += 1
            return FakeResult([{"id": self.share_codes[code]["id"]}])

        if cleaned.startswith("SELECT c.code, c.schedule_id, c.user_id, c.expires_at"):
            code = params[0]
            share = self.share_codes.get(code)
            if not share:
                return FakeResult([])
            sched = self.schedules.get(share["schedule_id"])
            user = self.users.get(share["user_id"], {})
            row = {
                "code": share["code"],
                "schedule_id": share["schedule_id"],
                "user_id": share["user_id"],
                "expires_at": share["expires_at"],
                "schedule_name": sched["name"] if sched else None,
                "term": sched.get("term", "") if sched else "",
                "start_date": sched.get("start_date") if sched else None,
                "end_date": sched.get("end_date") if sched else None,
                "username": user.get("username", ""),
                "email": user.get("email", ""),
            }
            return FakeResult([row])

        if cleaned.startswith("SELECT COUNT(*) AS count FROM courses WHERE schedule_id=%s"):
            sched_id = params[0]
            count = len(self.courses.get(sched_id, []))
            return FakeResult([{"count": count}])

        if cleaned.startswith("SELECT id, name, term, start_date, end_date, background, variant_type FROM schedules WHERE id=%s"):
            sched = self.schedules.get(params[0])
            return FakeResult([sched] if sched else [])

        if cleaned.startswith("SELECT id FROM schedules WHERE user_id=%s AND name=%s LIMIT 1"):
            user_id, name = params
            for s in self.schedules.values():
                if s["user_id"] == user_id and s["name"] == name:
                    return FakeResult([{"id": s["id"]}])
            return FakeResult([])

        if cleaned.startswith("INSERT INTO schedules"):
            user_id, name, term, start_date, end_date, background = params
            new_id = self._next_schedule_id
            self._next_schedule_id += 1
            self.schedules[new_id] = {
                "id": new_id,
                "user_id": user_id,
                "name": name,
                "term": term,
                "start_date": start_date,
                "end_date": end_date,
                "background": background,
                "variant_type": "original",
            }
            return FakeResult([{"id": new_id}])

        if cleaned.startswith("INSERT INTO courses"):
            target_sched_id, src_sched_id = params
            src_courses = self.courses.get(src_sched_id, [])
            self.courses[target_sched_id] = list(src_courses)
            return FakeResult([], rowcount=len(src_courses))

        raise AssertionError(f"Unhandled SQL in FakeShareDb: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# ==================== 服务层测试 ====================

def test_create_share_code_success():
    db = FakeShareDb(schedules={1: {"id": 1, "user_id": 1, "name": "计算机课表", "term": "2026秋"}})
    res = schedule_share.create_or_get_share_code(db, user_id=1, schedule_id=1)
    assert len(res["code"]) == 6
    assert res["schedule_name"] == "计算机课表"
    assert res["reused"] is False


def test_create_share_code_reused_if_active():
    active_code = "AB2345"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "计算机课表", "term": "2026秋"}},
        share_codes={active_code: {"id": 1, "code": active_code, "schedule_id": 1, "user_id": 1,
                                   "expires_at": datetime.now(UTC) + timedelta(days=5)}}
    )
    res = schedule_share.create_or_get_share_code(db, user_id=1, schedule_id=1)
    assert res["code"] == active_code
    assert res["reused"] is True


def test_create_share_code_rejects_unowned_schedule():
    db = FakeShareDb(schedules={1: {"id": 1, "user_id": 999, "name": "他人课表"}})
    with pytest.raises(ShareError) as err:
        schedule_share.create_or_get_share_code(db, user_id=1, schedule_id=1)
    assert err.value.code == "NOT_FOUND"


def test_get_share_info_valid():
    code = "CD7890"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "计算机课表", "term": "2026秋",
                        "start_date": date(2026, 9, 1), "end_date": date(2027, 1, 20)}},
        courses={1: [{"name": "C语言"}, {"name": "高数"}]},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=5)}}
    )
    info = schedule_share.get_share_info(db, code)
    assert info["name"] == "计算机课表"
    assert info["course_count"] == 2
    assert info["creator_name"] == "alice"


def test_get_share_info_expired():
    code = "OLD123"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "计算机课表"}},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) - timedelta(hours=1)}}
    )
    with pytest.raises(ShareError) as err:
        schedule_share.get_share_info(db, code)
    assert err.value.code == "EXPIRED"


def test_get_share_info_deleted():
    code = "GONE99"
    db = FakeShareDb(
        schedules={},  # 原课表已被删除
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=2)}}
    )
    with pytest.raises(ShareError) as err:
        schedule_share.get_share_info(db, code)
    assert err.value.code == "DELETED"


def test_import_shared_schedule_success():
    code = "IMP123"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "计算机课表", "term": "2026秋",
                        "start_date": "2026-09-01", "end_date": "2027-01-20", "background": ""}},
        courses={1: [{"name": "高数"}, {"name": "英语"}]},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=3)}}
    )
    # user_id 2 (Bob) 导入 user_id 1 的课表
    res = schedule_share.import_shared_schedule(db, user_id=2, code=code)
    assert res["name"] == "计算机课表"
    assert res["courses_imported"] == 2
    assert res["schedule_id"] != 1
    # 验证新课表属于 user_id 2
    new_sched = db.schedules[res["schedule_id"]]
    assert new_sched["user_id"] == 2


def test_import_shared_schedule_duplicate_name_suffix():
    code = "IMP456"
    db = FakeShareDb(
        schedules={
            1: {"id": 1, "user_id": 1, "name": "默认课表", "term": "2026秋",
                "start_date": None, "end_date": None, "background": ""},
            2: {"id": 2, "user_id": 2, "name": "默认课表", "term": "2026秋",
                "start_date": None, "end_date": None, "background": ""},
        },
        courses={1: [{"name": "物理"}]},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=3)}}
    )
    res = schedule_share.import_shared_schedule(db, user_id=2, code=code)
    assert res["name"] == "默认课表 (导入)"


def test_import_rejects_self():
    code = "MINE99"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "我的课表"}},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=3)}}
    )
    with pytest.raises(ShareError) as err:
        schedule_share.import_shared_schedule(db, user_id=1, code=code)
    assert err.value.code == "SELF_IMPORT"


# ==================== HTTP 端点测试 ====================

@pytest.fixture
def client_with_user():
    from app.auth import get_current_user
    from app.main import app
    user = {"id": 2, "username": "bob", "email": "bob@test.com"}
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_share_endpoint(client_with_user, monkeypatch):
    from app.routers import schedule_share as router_mod
    db = FakeShareDb(schedules={5: {"id": 5, "user_id": 2, "name": "测试课表", "term": ""}})
    monkeypatch.setattr(router_mod, "connect", lambda: db)

    resp = client_with_user.post("/api/schedules/5/share")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["code"]) == 6
    assert data["schedule_name"] == "测试课表"


def test_preview_endpoint(client_with_user, monkeypatch):
    from app.routers import schedule_share as router_mod
    code = "PREV12"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "高等物理", "term": "2026秋",
                        "start_date": "2026-09-01", "end_date": "2027-01-20"}},
        courses={1: [{"name": "热学"}]},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=4)}}
    )
    monkeypatch.setattr(router_mod, "connect", lambda: db)

    resp = client_with_user.get(f"/api/schedules/share/{code}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "高等物理"
    assert resp.json()["course_count"] == 1


def test_import_endpoint(client_with_user, monkeypatch):
    from app.routers import schedule_share as router_mod
    code = "IMP789"
    db = FakeShareDb(
        schedules={1: {"id": 1, "user_id": 1, "name": "分享课表", "term": "",
                        "start_date": None, "end_date": None, "background": ""}},
        courses={1: [{"name": "线性代数"}]},
        share_codes={code: {"id": 1, "code": code, "schedule_id": 1, "user_id": 1,
                            "expires_at": datetime.now(UTC) + timedelta(days=4)}}
    )
    monkeypatch.setattr(router_mod, "connect", lambda: db)

    resp = client_with_user.post(f"/api/schedules/share/{code}/import")
    assert resp.status_code == 200
    assert resp.json()["courses_imported"] == 1
