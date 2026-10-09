"""Read-only CCSUT directory and semester timetable access."""
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from Crypto.Cipher import AES

from ..html_parser import parse_ccsut_report, parse_qiangzhi_json
from ..parser import parse_weeks
from ..settings import ROOT

BASE = "https://tls.ccsut.cn"
CONFIG_FILE = ROOT / "data" / "academic" / "connection.enc"
KEY_FILE = CONFIG_FILE.with_name("credential.key")
TERM_RE = re.compile(r"^\d{4}-\d{4}-[12]$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,200}$")
_lock = threading.RLock()
_generation = 0
_config_version = None
_refresh_locks = {}
_students = OrderedDict()
_cache = OrderedDict()


class AcademicError(Exception):
    def __init__(self, code, message, status=502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _now():
    return datetime.now(UTC).isoformat()


def _key():
    dedicated = os.getenv("ACADEMIC_CREDENTIAL_SECRET", "")
    if dedicated:
        if len(dedicated) < 32:
            raise AcademicError("connection_not_configured", "School encryption secret must contain at least 32 characters", 503)
        return hashlib.sha256(("ccsut:" + dedicated).encode()).digest()
    try:
        key = KEY_FILE.read_bytes()
    except FileNotFoundError:
        secret = os.getenv("ADMIN_SESSION_SECRET", "")
        if len(secret) < 32:
            raise AcademicError("connection_not_configured", "Configure the administrator session secret first", 503)
        # Preserve the legacy encryption bytes on the first upgrade, then persist
        # them independently so later admin session rotation cannot destroy access.
        key = hashlib.sha256(("ccsut:" + secret).encode()).digest()
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(KEY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            key = KEY_FILE.read_bytes()
        else:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(key)
    if len(key) != 32:
        raise AcademicError("connection_unreadable", "School encryption key file is invalid", 503)
    return key


def _sync_connection_version():
    global _config_version, _generation
    try:
        stat = CONFIG_FILE.stat()
        version = (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        version = None
    with _lock:
        if version != _config_version:
            _config_version = version
            _generation += 1
            _cache.clear()


def connection_headers():
    _sync_connection_version()
    cookie = os.getenv("CCSUT_COOKIE", "").strip()
    agent = os.getenv("CCSUT_USER_AGENT", "Mozilla/5.0")
    if CONFIG_FILE.exists():
        try:
            raw = CONFIG_FILE.read_bytes()
            cipher = AES.new(_key(), AES.MODE_GCM, nonce=raw[:12])
            config = json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
            cookie, agent = config["cookie"], config["user_agent"]
        except AcademicError:
            raise
        except Exception as error:
            raise AcademicError("connection_unreadable", "教务连接配置无法读取，请重新配置", 503) from error
    if not cookie:
        raise AcademicError("connection_not_configured", "管理员尚未连接学校教务系统", 503)
    return {"Cookie": cookie, "User-Agent": agent, "X-Requested-With": "XMLHttpRequest"}


def save_connection(cookie, user_agent):
    global _generation
    if not cookie.strip() or "\r" in cookie or "\n" in cookie:
        raise AcademicError("invalid_cookie", "教务会话格式无效", 422)
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=os.urandom(12))
    raw, tag = cipher.encrypt_and_digest(json.dumps({"cookie": cookie.strip(), "user_agent": user_agent}).encode())
    with _lock:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_FILE.with_name(f"connection-{os.urandom(8).hex()}.tmp")
        temporary.write_bytes(cipher.nonce + tag + raw)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(CONFIG_FILE)
        _generation += 1
        _cache.clear()

    try:
        from .academic_directory import ensure_initial_refresh
        ensure_initial_refresh()
    except Exception:
        # The verified connection remains usable if the refresh queue is unavailable.
        logging.getLogger(__name__).exception('School directory initial refresh unavailable')


def parse_report(html, term):
    try:
        return parse_ccsut_report(html, term)
    except ValueError as error:
        raise AcademicError("report_invalid", str(error)) from error


class CcsutClient:
    def __init__(self, headers=None, transport=None):
        self.deadline = time.monotonic() + 60
        self.client = httpx.Client(headers=headers or connection_headers(), timeout=20,
                                   follow_redirects=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def request(self, method, path, **kwargs):
        url = urljoin(BASE, path)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "tls.ccsut.cn":
            raise AcademicError("upstream_url_invalid", "教务返回了异常地址")
        try:
            from .academic_rate_limit import acquire
            acquire(self.deadline)
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise AcademicError("upstream_timeout", "教务查询耗时过长，请稍后重试", 504)
            with self.client.stream(method, url, timeout=min(20, remaining), **kwargs) as response:
                if response.status_code in (301, 302, 303, 307, 308) or response.status_code in (401, 403):
                    raise AcademicError("connection_expired", "学校登录已过期或无查询权限，请管理员重新连接", 409)
                if response.status_code != 200:
                    raise AcademicError("upstream_failed", "学校教务系统暂时无法响应")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 3_000_000:
                        raise AcademicError("upstream_too_large", "教务响应超过允许大小")
                    chunks.append(chunk)
                content = b"".join(chunks).decode("utf-8")
        except AcademicError:
            raise
        except (httpx.HTTPError, UnicodeError) as error:
            raise AcademicError("upstream_failed", "学校教务连接失败，请稍后重试") from error
        if "统一身份认证" in content or "扫码登录" in content:
            raise AcademicError("connection_expired", "学校登录已过期，请管理员重新连接", 409)
        return content

    def json(self, method, path, **kwargs):
        try:
            data = json.loads(self.request(method, path, **kwargs))
        except json.JSONDecodeError as error:
            raise AcademicError("upstream_invalid", "教务返回了非 JSON 数据，请检查连接") from error
        if isinstance(data, dict) and data.get("ret") != 0:
            raise AcademicError("upstream_denied", "教务未允许本次查询或学期尚未发布", 409)
        return data

    def grades(self):
        soup = BeautifulSoup(self.request("GET", "/admin/jwxtgld/kbcx/xskblist"), "html.parser")
        values = [a.get_text(strip=True) for a in soup.select(".list_sslct a")]
        grades = [v for v in values if re.fullmatch(r"20\d{2}", v)]
        if not grades:
            raise AcademicError("directory_invalid", "无法识别学校年级目录")
        return grades

    def search(self, *, grade, name="", class_name="", major_name="", keyword=""):
        tree = self.json("POST", "/admin/jwxtgld/xscx/getXssjYxxx",
                         data={"sznj": grade, "xm": name})
        if not isinstance(tree, list):
            raise AcademicError("directory_invalid", "学校班级目录格式异常")
        if keyword:
            matched = []
            for dept in tree:
                majors = []
                for major in dept.get("zyxxList") or []:
                    classes = [c for c in major.get("bjxxList") or []
                               if keyword in " ".join((grade, dept.get("yxmc", ""), major.get("zymc", ""), c.get("bjmc", "")))]
                    if classes:
                        majors.append(dict(major, bjxxList=classes))
                if majors:
                    matched.append(dict(dept, zyxxList=majors))
            if not matched:
                return self.search(grade=grade, name=keyword)
            tree = matched
        result, counts = [], []
        classes = []
        for dept in tree:
            for major in dept.get("zyxxList") or []:
                if major_name and major_name not in major.get("zymc", ""):
                    continue
                for cls in major.get("bjxxList") or []:
                    if class_name and class_name not in cls.get("bjmc", ""):
                        continue
                    classes.append((dept, major, cls))
        if len(classes) > 80:
            raise AcademicError("search_too_broad", "请补充班级或姓名以缩小查询范围", 422)
        for dept, major, cls in classes:
            if len(result) >= 100:
                break
            soup = BeautifulSoup(self.request("GET", "/admin/jwxtgld/kbcx/xsxxlist", params={
                "sznj": grade, "yxid": dept["id"], "zyid": major["id"], "bjid": cls["id"]}), "html.parser")
            links = soup.select(".xskb-link")
            ids = set()
            for link in links:
                sid, student_name, term = link.get("data-id", ""), link.get("data-name", ""), link.get("data-xnxq", "")
                if not ID_RE.fullmatch(sid) or not student_name or not TERM_RE.fullmatch(term):
                    raise AcademicError("directory_invalid", "学生目录字段不完整")
                ids.add(sid)
                fields = link.select(".text-class")
                student = {"id": sid, "name": student_name, "student_number_display": fields[0].get_text(strip=True) if fields else "",
                           "grade": grade, "department_name": dept.get("yxmc", ""),
                           "major_name": major.get("zymc", ""), "class_name": cls.get("bjmc", ""),
                           "class_id": cls["id"], "default_term": term}
                if name and name not in student_name:
                    continue
                result.append(student)
                if len(result) >= 100:
                    break
            counts.append({"class_name": cls.get("bjmc", ""), "parsed_students": len(ids)})
        return {"students": result, "classes": counts, "fetched_at": _now(), "truncated": len(result) >= 100}

    def terms(self, sid, term):
        html = self.request("GET", "/admin/api/getKbxx", params={"userId": sid, "xnxq": term, "role": "xs", "xqid": ""})
        match = re.search(r"var xnxqList\s*=\s*'([^']*)'", html)
        terms = match[1].split(",") if match else []
        terms = [t for t in terms if TERM_RE.fullmatch(t)]
        if not terms:
            raise AcademicError("terms_invalid", "无法识别可查询的学期")
        return terms

    def schedule(self, sid, term):
        calendar = self.json("POST", "/admin/api/getZclistByXnxq",
                             data={"xnxq": term, "role": "xs", "userId": sid, "xqid": ""})
        data = calendar.get("data") if isinstance(calendar, dict) else None
        weeks = data.get("zclist") if isinstance(data, dict) else None
        if not isinstance(weeks, list) or not weeks:
            raise AcademicError("calendar_invalid", "学校未返回有效学期校历")
        try:
            entries = [(int(w["zc"]), date.fromisoformat(str(w["minrq"])[:10]),
                        date.fromisoformat(str(w["maxrq"])[:10])) for w in weeks]
            expected = sorted({week for week, _, _ in entries})
            if not all(1 <= week <= 30 for week in expected) or expected != list(range(1, max(expected) + 1)):
                raise ValueError("missing or invalid week")
            first = next(begin for week, begin, _ in entries if week == 1)
            if first.weekday() != 0:
                raise ValueError("first week must begin on Monday")
            for week, begin, finish in entries:
                if begin != first + timedelta(weeks=week - 1) or finish != begin + timedelta(days=6):
                    raise ValueError("calendar dates do not match week numbers")
            start = first.isoformat()
            end = max(finish for _, _, finish in entries).isoformat()
        except (KeyError, TypeError, ValueError) as error:
            raise AcademicError("calendar_invalid", "校历周次格式异常") from error
        url_data = self.json("GET", "/admin/pkgl/xskb/getReportUrl",
                             params={"id": sid, "xnxq": term, "ydd": "1", "mbzc": "", "from": "1"})
        try:
            html = self.request("GET", url_data["data"]["url"])
        except (KeyError, TypeError) as error:
            raise AcademicError("report_invalid", "学校未返回有效报表地址") from error
        try:
            parsed = parse_report(html, term)
        except AcademicError as error:
            if error.code not in ("report_invalid", "report_paged"):
                raise
            parsed = {"name": "长沙工业学院教务课表", "term": term, "courses": [], "notes": []}
        # A fully parsed semester matrix is usable without a pagination marker.
        # The parser rejects explicit pagination and unrecognised course cells.
        # Empty reports still need weekly proof.
        report_weeks = {week for course in parsed["courses"] for week in course["weeks"]}
        if parsed["courses"] and report_weeks.issubset(set(expected)):
            parsed.update(start_date=start, end_date=end, section_times=data.get("jcsjszList") or [],
                          fetched_at=_now(), source="ccsut_semester_report", complete=True,
                          completeness="semester_report", expected_weeks=expected, completed_weeks=[],
                          warnings=[])
            return parsed
        rows, completed = [], []
        for week in expected:
            response = self.json("GET", "/admin/api/getXskb", params={
                "xnxq": term, "userId": sid, "xqid": "", "week": week, "role": "xs"})
            if not isinstance(response, dict):
                raise AcademicError("schedule_invalid", "学校周课表格式异常")
            if "data" not in response:
                items = []  # Observed school contract: ret=0 with no data is an empty numbered week.
            elif isinstance(response["data"], dict) and isinstance(response["data"].get("kckbData"), list):
                items = response["data"]["kckbData"]
            else:
                raise AcademicError("schedule_invalid", "学校周课表格式异常")
            for item in items:
                try:
                    valid = (isinstance(item, dict) and bool(item.get("kcmc")) and
                             item.get("xnxq", term) == term and
                             1 <= int(item.get("xingqi")) <= 7 and
                             1 <= int(item.get("djc")) <= 12 and
                             week in parse_weeks(str(item.get("zcstr") or item.get("zc") or "")))
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    raise AcademicError("schedule_invalid", "学校课程字段或周次不完整")
            rows.extend(items)
            completed.append(week)
        verified = parse_qiangzhi_json({"data": rows}, exact=True)
        if rows and not verified:
            raise AcademicError("schedule_invalid", "学校课程数据无法识别")
        authoritative = verified["courses"] if verified else []
        def slots(courses):
            return {(c["name"], c["teacher"], c["room"], c["weekday"], section, week)
                    for c in courses for section in range(c["start_section"], c["end_section"] + 1)
                    for week in c["weeks"]}
        if parsed["courses"] and not authoritative:
            raise AcademicError("schedule_mismatch", "报表有课程但逐周接口为空，未发布不完整查询结果")
        matched = slots(parsed["courses"]) == slots(authoritative)
        parsed["courses"] = authoritative
        parsed["report_matched"] = matched
        parsed.update(start_date=start, end_date=end, section_times=data.get("jcsjszList") or [],
                      fetched_at=_now(), source="ccsut_verified", complete=True,
                      completeness="weekly_verified", expected_weeks=expected, completed_weeks=completed,
                      warnings=[] if matched else ["报表与逐周数据有差异，已采用完整逐周数据。"])
        return parsed


def _put(mapping, key, value, maximum):
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > maximum:
        mapping.popitem(last=False)


@contextmanager
def _database():
    path = ROOT / "data" / "academic" / "cache.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    if os.name != "nt":
        path.chmod(0o600)
    db.execute("CREATE TABLE IF NOT EXISTS snapshots (kind TEXT, key TEXT, payload TEXT, updated REAL, PRIMARY KEY(kind,key))")
    try:
        with db:
            yield db
    finally:
        db.close()


def _persist(kind, key, payload):
    with _database() as db:
        db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                   (kind, key, json.dumps(payload, ensure_ascii=False), time.time()))
        maximum = 5000 if kind == "student" else 128
        db.execute("DELETE FROM snapshots WHERE kind=? AND key NOT IN "
                   "(SELECT key FROM snapshots WHERE kind=? ORDER BY updated DESC LIMIT ?)", (kind, kind, maximum))


def _restore(kind, key):
    with _database() as db:
        row = db.execute("SELECT payload FROM snapshots WHERE kind=? AND key=?", (kind, key)).fetchone()
    return json.loads(row[0]) if row else None




def available_terms(sid):
    student = student_context(sid)
    try:
        with CcsutClient() as client:
            values = client.terms(sid, student["default_term"])
        _persist("terms", sid, values)
        return {"terms": values, "stale": False}
    except AcademicError:
        with _database() as db:
            rows = db.execute("SELECT key FROM snapshots WHERE kind='schedule'").fetchall()
        values = sorted({r[0].split(":", 1)[1] for r in rows if r[0].startswith(sid + ":")}, reverse=True)
        if values:
            return {"terms": values, "stale": True}
        raise


def browser_status():
    path = ROOT / "data" / "academic" / "browser-status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: data[k] for k in ("state", "checked_at", "message", "error_type", "cookie_rotated") if k in data}
    except (OSError, ValueError, TypeError):
        return {"state": "not_started"}


def search_students(grade, name, class_name, major_name=""):
    from . import academic_directory
    local = academic_directory.search(grade=grade, name=name, class_name=class_name, major_name=major_name)
    if local is not None:
        return local
    try:
        with CcsutClient() as client:
            result = client.search(grade=grade, name=name, class_name=class_name, major_name=major_name)
    except AcademicError as error:
        with _database() as db:
            rows = db.execute("SELECT payload FROM snapshots WHERE kind='student'").fetchall()
        students = [json.loads(row[0]) for row in rows]
        students = [s for s in students if s["grade"] == grade and name in s["name"] and class_name in s["class_name"]
                    and major_name in s.get("major_name", "")]
        if not students:
            raise
        result = {"students": students, "classes": [], "stale": True,
                  "refresh_error": {"code": error.code, "message": error.message}}

    with _lock:
        for student in result["students"]:
            _put(_students, student["id"], student, 5000)
            _persist("student", student["id"], student)
    return result


def student_context(sid):
    _sync_connection_version()
    from . import academic_directory
    student = academic_directory.student(sid)
    if student:
        return student
    with _lock:
        student = _students.get(sid)
        if student:
            return dict(student)
    student = _restore("student", sid)
    if student:
        return student
    raise AcademicError("student_not_selected", "请先搜索并选择学生", 404)


def get_schedule(sid, term, refresh=False):
    key = (_generation, sid, term)
    with _lock:
        cached = _cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < 900:
            return dict(cached[1], cached=True, stale=False)
        entry = _refresh_locks.setdefault(key, [threading.Lock(), 0])
        entry[1] += 1
    began = time.monotonic()
    acquired = False
    try:
        acquired = entry[0].acquire(timeout=5)
        if not acquired:
            raise AcademicError("query_busy", "正在核验此课表，请稍后重试", 429)
        # Concurrent forced refreshes share the snapshot fetched since they began.
        with _lock:
            cached = _cache.get(key)
            if cached and cached[0] >= began:
                return dict(cached[1], cached=True, stale=False)
        return _get_schedule(sid, term, refresh)
    finally:
        if acquired:
            entry[0].release()
        with _lock:
            entry[1] -= 1
            if not entry[1]:
                _refresh_locks.pop(key, None)


def _get_schedule(sid, term, refresh=False):
    student = student_context(sid)
    key = (_generation, sid, term)
    with _lock:
        cached = _cache.get(key)
    if cached and not refresh and time.monotonic() - cached[0] < 900:
        return dict(cached[1], cached=True, stale=False)
    if not cached:
        restored = _restore("schedule", sid + ":" + term)
        if restored:
            cached = (0, restored)
    try:
        with CcsutClient() as client:
            terms = client.terms(sid, student["default_term"])
            if term not in terms:
                raise AcademicError("term_unavailable", "该学期课表尚未发布", 422)
            result = dict(client.schedule(sid, term), student=student)
    except AcademicError as error:
        if cached:
            return dict(cached[1], cached=True, stale=True, refresh_error={"code": error.code, "message": error.message})
        raise
    _persist("schedule", sid + ":" + term, result)
    with _lock:
        _put(_cache, key, (time.monotonic(), result), 128)
    return dict(result, cached=False, stale=False)



def search_keyword(query):
    query = query.strip()
    match = re.match(r"^(20\d{2}|\d{2})(?:级)?", query)
    requested_grade = None
    if match:
        requested_grade = match[1] if len(match[1]) == 4 else "20" + match[1]
        if match[0] == query:
            query = ""
    from . import academic_directory
    local_query = query[match.end():].strip() if match and query else query
    local = academic_directory.search(query=local_query, grade=requested_grade)
    if local is not None:
        return local
    try:
        with CcsutClient() as client:
            grades = client.grades()
            _persist("grades", "all", grades)
            if requested_grade:
                grades = [g for g in grades if g == requested_grade]
            students, truncated = [], False
            for grade in grades:
                result = client.search(grade=grade, keyword=local_query)
                students.extend(result["students"])
                if result.get("truncated") or len(students) >= 100:
                    truncated = True
                    break
        students = students[:100]
        with _lock:
            for student in students:
                _put(_students, student["id"], student, 5000)
                _persist("student", student["id"], student)
        return {"students": students, "truncated": truncated, "fetched_at": _now(), "stale": False}
    except AcademicError as error:
        with _database() as db:
            rows = db.execute("SELECT payload FROM snapshots WHERE kind='student'").fetchall()
        students = [json.loads(r[0]) for r in rows]
        students = [s for s in students if (not requested_grade or s["grade"] == requested_grade)
                    and query in " ".join(str(s.get(k, "")) for k in
                                          ("name", "major_name", "class_name", "grade", "department_name"))]
        if not students:
            raise
        return {"students": students[:100], "truncated": len(students) > 100, "stale": True,
                "refresh_error": {"code": error.code, "message": error.message}}
