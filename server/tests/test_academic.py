import httpx
import pytest

from app.services import academic


def report(cell, pages="1"):
    return f'<input id="report1_totalpage_input" value="{pages}"><table><tr><td>节次</td>' + "".join(
        f"<td>星期{d}</td>" for d in "一二三四五六日") + f'</tr><tr><td>5</td><td rowspan="2">{cell}</td>' + "<td></td>" * 6 + "</tr><tr><td>6</td></tr></table>"


def test_report_wrapped_names_and_location_changes():
    result = academic.parse_report(report(
        "计算机课程设<br>计<br><br>李老师【1-3(单)周】<br>北201<br><br>"
        "计算机课程设<br>计<br><br>李老师【2周】<br>南301<br>"), "2026-2027-1")
    assert len(result["courses"]) == 2
    first, second = result["courses"]
    assert first["name"] == second["name"] == "计算机课程设计"
    assert first["weeks"] == [1, 3]
    assert second["weeks"] == [2]
    assert first["room"] == "北201"
    assert second["room"] == "南301"
    assert first["start_section"] == 5 and first["end_section"] == 6


@pytest.mark.parametrize("html", [report("课程", "2"), report("无法识别的安排"), "<h1>登录</h1>"])
def test_unrecognised_report_never_claims_complete(html):
    with pytest.raises(academic.AcademicError):
        academic.parse_report(html, "2026-2027-1")


def test_real_nested_course_json():
    from app.html_parser import parse_qiangzhi_json
    result = parse_qiangzhi_json({"ret": 0, "data": {"kckbData": [{
        "kcmc": "示例课", "tmc": "教师", "croommc": "教室", "xingqi": 2, "djc": 1,
        "zcstr": "1,3", "xnxq": "2025-2026-2"}]}})
    assert result["term"] == "2025-2026学年第2学期"
    assert result["courses"][0]["weeks"] == [1, 3]


def client(handler):
    return academic.CcsutClient({"Cookie": "test-session"}, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://auth.ccsut.cn/login"}),
    httpx.Response(200, text="统一身份认证"),
    httpx.Response(403),
])
def test_expired_connection_is_distinct_from_user_login(response):
    with client(lambda _: response) as c:
        with pytest.raises(academic.AcademicError) as error:
            c.request("GET", "/admin/api/getXskb")
    assert error.value.code == "connection_expired"
    assert error.value.status == 409


def test_report_url_cannot_send_school_cookie_elsewhere():
    requests = []
    with client(lambda r: requests.append(r) or httpx.Response(200)) as c:
        with pytest.raises(academic.AcademicError):
            c.request("GET", "https://example.com/report")
    assert requests == []


def test_connection_encrypted_and_cache_invalidated(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "s" * 32)
    monkeypatch.delenv("CCSUT_COOKIE", raising=False)
    monkeypatch.setattr(academic, "CONFIG_FILE", tmp_path / "connection.enc")
    academic._students["test"] = {}
    academic._cache["test"] = {}
    academic.save_connection("cookie=test-value", "test-agent")
    assert b"test-value" not in academic.CONFIG_FILE.read_bytes()
    assert academic.connection_headers()["Cookie"] == "cookie=test-value"
    assert "test" in academic._students and not academic._cache
    raw = bytearray(academic.CONFIG_FILE.read_bytes())
    raw[-1] ^= 1
    academic.CONFIG_FILE.write_bytes(raw)
    with pytest.raises(academic.AcademicError) as error:
        academic.connection_headers()
    assert error.value.code == "connection_unreadable"


def timetable_handler(request):
    path = request.url.path
    if path.endswith("getZclistByXnxq"):
        return httpx.Response(200, json={"ret": 0, "data": {"zclist": [
            {"zc": "1", "minrq": "2026-09-07", "maxrq": "2026-09-13"},
            {"zc": "2", "minrq": "2026-09-14", "maxrq": "2026-09-20"}]}})
    if path.endswith("getReportUrl"):
        return httpx.Response(200, json={"ret": 0, "data": {"url": academic.BASE + "/report/sample"}})
    if path == "/report/sample":
        return httpx.Response(200, text=report("示例课<br><br>老师【1周】<br>教室<br>"))
    if path.endswith("getXskb"):
        if request.url.params["week"] == "2":
            return httpx.Response(200, json={"ret": 0})  # Observed empty week contract.
        return httpx.Response(200, json={"ret": 0, "data": {"kckbData": [
            {"kcmc": "示例课", "tmc": "老师", "croommc": "教室", "xingqi": 1,
             "djc": s, "zcstr": "1", "xnxq": "2026-2027-1"} for s in (5, 6)]}})
    raise AssertionError(path)


def weekly_fallback_handler(request):
    if request.url.path == "/report/sample":
        return httpx.Response(200, text=report("示例课<br><br>老师【1周】<br>教室<br>", pages="2"))
    return timetable_handler(request)


def test_schedule_verifies_every_week_including_empty():
    with client(weekly_fallback_handler) as c:
        result = c.schedule("student123", "2026-2027-1")
    assert result["complete"] and result["completeness"] == "weekly_verified"
    assert result["completed_weeks"] == [1, 2]
    assert result["start_date"] == "2026-09-07"
    assert len(result["courses"]) == 1


def test_failed_week_cannot_be_published_as_complete():
    def handler(request):
        if request.url.path.endswith("getXskb") and request.url.params["week"] == "2":
            return httpx.Response(500)
        return weekly_fallback_handler(request)
    with client(handler) as c:
        with pytest.raises(academic.AcademicError) as error:
            c.schedule("student123", "2026-2027-1")
    assert error.value.code == "upstream_failed"


def test_unrecognised_week_shape_is_not_empty():
    def handler(request):
        if request.url.path.endswith("getXskb"):
            return httpx.Response(200, json={"ret": 0, "data": {"unexpected": []}})
        return weekly_fallback_handler(request)
    with client(handler) as c:
        with pytest.raises(academic.AcademicError):
            c.schedule("student123", "2026-2027-1")


def test_stale_snapshot_preserved_on_refresh_error(monkeypatch):
    academic._sync_connection_version()
    academic._students.clear()
    academic._cache.clear()
    academic._students["student123"] = {"id": "student123", "default_term": "2026-2027-1"}
    snapshot = {"courses": [{"name": "old"}], "complete": True, "fetched_at": "old"}
    academic._cache[(academic._generation, "student123", "2026-2027-1")] = (0, snapshot)
    def fail():
        raise academic.AcademicError("connection_expired", "过期", 409)
    monkeypatch.setattr(academic, "CcsutClient", fail)
    result = academic.get_schedule("student123", "2026-2027-1", refresh=True)
    assert result["stale"] and result["courses"] == snapshot["courses"]
    assert result["refresh_error"]["code"] == "connection_expired"
    assert snapshot.get("stale") is None


def test_directory_same_name_candidates_and_masked_number():
    def handler(request):
        if request.url.path.endswith("getXssjYxxx"):
            return httpx.Response(200, json=[{"id": "dept", "yxmc": "学院", "zyxxList": [
                {"id": "major", "zymc": "专业", "bjxxList": [{"id": "class", "bjmc": "24计科1班"}]}]}])
        return httpx.Response(200, text="".join(
            f'<a class="xskb-link" data-id="student00{i}" data-name="张同学" data-xnxq="2026-2027-1">'
            '<div class="text-class">2024****0001</div></a>' for i in range(2)))
    with client(handler) as c:
        result = c.search(grade="2024", name="张同学")
    assert len(result["students"]) == 2
    assert result["classes"][0]["parsed_students"] == 2
    assert all(s["student_number_display"] == "2024****0001" for s in result["students"])


def test_routes_use_separate_user_and_admin_auth():
    from app.auth import get_current_user
    from app.routers.academic import router
    from app.routers.admin import require_superadmin
    user_routes = [r for r in router.routes if r.path.startswith("/api/academic")]
    admin_routes = [r for r in router.routes if r.path.startswith("/api/admin")]
    assert all(any(d.call == get_current_user for d in r.dependant.dependencies) for r in user_routes)
    assert all(any(d.call == require_superadmin for d in r.dependant.dependencies) for r in admin_routes)


def test_webview_and_backend_share_report_parser():
    from app.html_parser import parse_html_schedule
    html = report("计算机课程设<br>计<br><br>李老师【18周】<br>北201<br>")
    direct = academic.parse_report(html, "2026-2027学年第1学期")
    imported = parse_html_schedule(html)
    assert imported["courses"] == direct["courses"]
    assert imported["courses"][0]["name"] == "计算机课程设计"

def test_exact_school_json_keeps_single_section_and_location_variants():
    from app.html_parser import parse_qiangzhi_json
    result = parse_qiangzhi_json({"data": [
        {"kcmc": "算法设计", "tmc": "老师", "croommc": room, "xingqi": 1,
         "djc": 5, "zcstr": "1", "xnxq": "2026-2027-1"} for room in ("A", "B")
    ]}, exact=True)
    assert len(result["courses"]) == 2
    assert all(c["start_section"] == c["end_section"] == 5 for c in result["courses"])


def test_invalid_course_row_prevents_complete_snapshot():
    def handler(request):
        if request.url.path.endswith("getXskb"):
            return httpx.Response(200, json={"ret": 0, "data": {"kckbData": [{"kcmc": "缺少字段"}]}})
        return weekly_fallback_handler(request)
    with client(handler) as c:
        with pytest.raises(academic.AcademicError) as error:
            c.schedule("student123", "2026-2027-1")
    assert error.value.code == "schedule_invalid"




@pytest.fixture(autouse=True)
def isolated_snapshot_store(tmp_path, monkeypatch):
    monkeypatch.setattr(academic, "ROOT", tmp_path)


def test_restart_and_expired_connection_preserve_complete_schedule(monkeypatch):
    academic._sync_connection_version()
    academic._students.clear()
    academic._cache.clear()
    student = {"id": "persisted123", "default_term": "2026-2027-1", "grade": "2024",
               "name": "同学", "class_name": "24计科1班"}
    snapshot = {"courses": [{"name": "算法"}], "complete": True, "fetched_at": "2026-10-08"}
    academic._persist("student", student["id"], student)
    academic._persist("schedule", student["id"] + ":2026-2027-1", snapshot)
    def fail():
        raise academic.AcademicError("connection_expired", "过期", 409)
    monkeypatch.setattr(academic, "CcsutClient", fail)
    assert academic.available_terms(student["id"]) == {"terms": ["2026-2027-1"], "stale": True}
    result = academic.get_schedule(student["id"], "2026-2027-1")
    assert result["stale"] and result["complete"] and result["fetched_at"] == snapshot["fetched_at"]
    directory = academic.search_students("2024", "同学", "24计科")
    assert directory["stale"] and directory["students"] == [student]


def test_cache_rotation_keeps_selected_students(monkeypatch, tmp_path):
    monkeypatch.setattr(academic, "CONFIG_FILE", tmp_path / "connection.enc")
    academic._students["selected123"] = {"id": "selected123"}
    academic.CONFIG_FILE.write_bytes(b"rotated")
    academic._sync_connection_version()
    assert academic.student_context("selected123")["id"] == "selected123"


def test_worker_status_does_not_expose_extra_fields(tmp_path):
    path = tmp_path / "data" / "academic" / "browser-status.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"state":"connected","cookie":"secret"}', encoding="utf-8")
    assert academic.browser_status() == {"state": "connected"}


def test_binding_is_scoped_to_authenticated_user(monkeypatch):
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth import get_current_user
    from app.routers import academic as routes
    from app.services import academic_binding as bindings

    stored = {}
    identity = {"id": 901}
    class Result:
        def __init__(self, value=None):
            self.value = value
        def fetchone(self):
            return self.value
    class Database:
        def execute(self, sql, params):
            if sql.startswith("SELECT"):
                return Result(stored.get(params[0]))
            if "INSERT" in sql:
                import json
                stored[params[0]] = {"student": json.loads(params[1]), "updated_at": "2026-10-08", "revision": 1, "last_synced_at": None, "last_synced_term": None}
                return Result(stored[params[0]])
            if "DELETE" in sql:
                stored.pop(params[0], None)
            return Result()
    @contextmanager
    def connect():
        yield Database()
    monkeypatch.setattr(bindings, "connect", connect)
    monkeypatch.setattr(academic, "student_context", lambda sid: {"id": sid, "name": "同学"})
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: identity
    with TestClient(app) as client:
        assert client.get("/api/academic/binding").json() == {"student": None}
        assert client.put("/api/academic/binding", json={"student_id": "student123"}).status_code == 200
        assert client.get("/api/academic/binding").json()["student"]["id"] == "student123"
        identity["id"] = 902
        assert client.get("/api/academic/binding").json() == {"student": None}
        identity["id"] = 901
        assert client.delete("/api/academic/binding").status_code == 200
        assert client.get("/api/academic/binding").json() == {"student": None}



@pytest.mark.parametrize("query,expected", [("24", [("2024", "")]),
    ("25", [("2025", "")]), ("24计科", [("2024", "24计科")]),
    ("张三", [("2025", "张三"), ("2024", "张三")])])
def test_unified_search_resolves_short_grades_and_chinese(query, expected, monkeypatch):
    calls = []
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def grades(self):
            return ["2025", "2024"]
        def search(self, *, grade, keyword):
            calls.append((grade, keyword))
            return {"students": [], "truncated": False}
    monkeypatch.setattr(academic, "CcsutClient", Client)
    result = academic.search_keyword(query)
    assert calls == expected
    assert not result["stale"]


@pytest.mark.parametrize("stale", [False, True])
def test_binding_sync_writes_only_complete_new_snapshot(monkeypatch, stale):
    from contextlib import contextmanager

    from fastapi import HTTPException

    from app.routers import academic as routes
    from app.services import academic_binding as bindings

    association = {"student": {"id": "student123", "name": "同学"}, "revision": 1, "updated_at": "2026-10-08"}
    monkeypatch.setattr(bindings, "read_binding", lambda uid: association)
    monkeypatch.setattr(academic, "get_schedule", lambda *args: {
        "stale": stale, "complete": True, "start_date": "2026-09-07", "end_date": "2027-01-24", "courses": []})
    written, sql_calls = [], []
    class Database:
        def execute(self, sql, params):
            sql_calls.append((sql, params))
            self.sql = sql
            return self
        def fetchone(self):
            if "SELECT student,revision" in self.sql:
                return association
            if "UPDATE academic_bindings" in self.sql:
                return {"last_synced_at": "2026-10-08"}
            return None
    @contextmanager
    def connect():
        yield Database()
    monkeypatch.setattr(bindings, "connect", connect)
    def write(db, **kwargs):
        written.append(kwargs)
        return {"schedule_id": 123, "imported": 33}
    monkeypatch.setattr(bindings, "write_schedule", write)
    monkeypatch.setattr(bindings.schedule_backups, "capture", lambda db, user_id: None)
    if stale:
        with pytest.raises(HTTPException):
            bindings.sync(5, "2026-2027-1")
        assert not written
    else:
        result = bindings.sync(5, "2026-2027-1")
        assert result["schedule_id"] == 123
        assert written[0]["create_new"] and written[0]["exact"] and not written[0]["preserve_adjusted"]
        assert written[0]["user_id"] == 5
        assert sql_calls[-1][1] == (5, 123)
        assert "DELETE FROM schedules WHERE user_id=%s AND id<>%s" in sql_calls[-1][0]



def test_complete_semester_report_uses_three_requests_without_weekly_queries():
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("getXskb"):
            pytest.fail("complete report must not trigger weekly fetching")
        return timetable_handler(request)
    with client(handler) as c:
        result = c.schedule("student123", "2026-2027-1")
    assert result["complete"] and result["completeness"] == "semester_report"
    assert result["completed_weeks"] == [] and len(result["courses"]) == 1
    assert len(requests) == 3


@pytest.mark.parametrize("cell,pages", [("", "1"), ("无法识别", "1"), ("示例课<br>老师【3周】<br>教室", "1")])
def test_ambiguous_or_empty_report_falls_back_to_all_weeks(cell, pages):
    weeks = []
    def handler(request):
        if request.url.path == "/report/sample":
            return httpx.Response(200, text=report(cell, pages))
        if request.url.path.endswith("getXskb"):
            weeks.append(request.url.params['week'])
        return timetable_handler(request)
    with client(handler) as c:
        result = c.schedule("student123", "2026-2027-1")
    assert result["complete"] and result["completeness"] == "weekly_verified"
    assert weeks == ['1', '2']


def test_report_without_explicit_single_page_marker_requires_weekly_verification():
    def handler(request):
        if request.url.path == '/report/sample':
            return httpx.Response(200, text=report("示例课<br>老师【1周】<br>教室").replace('<input id="report1_totalpage_input" value="1">',''))
        return timetable_handler(request)
    with client(handler) as c:
        result = c.schedule('student123','2026-2027-1')
    assert result['completeness'] == 'weekly_verified'


@pytest.mark.parametrize("weeks", [
    [{"zc": "2", "minrq": "2026-09-14", "maxrq": "2026-09-20"}],
    [{"zc": "1", "minrq": "2026-09-08", "maxrq": "2026-09-14"}],
    [{"zc": "1", "minrq": "2026-09-07", "maxrq": "2026-09-13"},
     {"zc": "2", "minrq": "2026-09-21", "maxrq": "2026-09-27"}],
    [{"zc": "1", "minrq": "2026-09-07", "maxrq": "2026-09-06"}],
])
def test_inconsistent_calendar_cannot_shift_course_dates(weeks):
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"ret": 0, "data": {"zclist": weeks}})
    with client(handler) as c:
        with pytest.raises(academic.AcademicError) as error:
            c.schedule("student123", "2026-2027-1")
    assert error.value.code == "calendar_invalid"
    assert len(requests) == 1
