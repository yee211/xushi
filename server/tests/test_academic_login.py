"""School credentials and administrator-controlled login lifecycle."""
import queue
import threading
import time
from urllib.parse import urlsplit

import pytest

from app.services import academic_login as login
from app.services.academic import AcademicError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-key-" + "x" * 40)
    monkeypatch.setattr(login, "DIRECTORY", tmp_path)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr("app.services.academic.CONFIG_FILE", tmp_path / "connection.enc")
    monkeypatch.setattr(login, "CREDENTIALS", tmp_path / "credentials.enc")
    monkeypatch.setattr(login, "BROWSER_SESSION", tmp_path / "browser-session.enc")
    monkeypatch.setattr(login, "MAINTENANCE", tmp_path / "maintenance.json")
    monkeypatch.setattr(login, "_stop_event", threading.Event())
    monkeypatch.setattr(login, "_thread", None)
    monkeypatch.setattr(login, "_commands", queue.Queue(maxsize=8))
    monkeypatch.setattr(login, "_state", {"state": "not_started", "message": "test"})
    monkeypatch.setattr(login.academic_mail, "connection_event", lambda state: None)


def test_credentials_are_encrypted_and_never_return_password():
    login.save_credentials("13800138000")
    assert b"13800138000" not in login.CREDENTIALS.read_bytes()
    assert login.credentials() == {"account": "13800138000"}
    result = login.status()
    assert result["account"] == "13800138000"
    assert "password" not in result
    login.delete_credentials()
    assert not login.status()["saved"]


def test_mail_events_only_when_relogin_is_required(monkeypatch):
    events = []
    monkeypatch.setattr(login.academic_mail, "connection_event", events.append)
    login.save_maintenance(enabled=True)
    login.update("waiting_code", "首次登录")
    login.update("retrying", "网络重试")
    assert events == []
    login.save_maintenance(last_verified_at="2026-10-09T14:00:00+00:00")
    login.update("waiting_code", "会话失效，需要验证码")
    login.update("connected", "恢复成功")
    login.update("stopped", "服务重启")
    assert events == ["needs_login", "connected"]
    login.save_maintenance(enabled=False)
    login.update("stopped", "管理员停止")
    assert events[-1] == "stopped"


def test_mail_storage_error_does_not_break_login(monkeypatch):
    def failed(state):
        raise OSError("存储不可用")
    monkeypatch.setattr(login.academic_mail, "connection_event", failed)
    login.update("connected", "连接成功")
    assert login.status()["state"] == "connected"


def test_changed_key_fails_closed(monkeypatch):
    monkeypatch.setenv("ACADEMIC_CREDENTIAL_SECRET", "x" * 40)
    login.save_credentials("13800138000")
    monkeypatch.setenv("ACADEMIC_CREDENTIAL_SECRET", "different-" + "y" * 40)
    with pytest.raises(AcademicError):
        login.credentials()
    assert "password" not in login.status()


class Running:
    def is_alive(self):
        return True


def test_code_only_accepted_in_current_waiting_job(monkeypatch):
    monkeypatch.setattr(login, "_thread", Running())
    login._state.update(job_id="job", state="waiting_code")
    with pytest.raises(AcademicError):
        login.command("submit_code", "old-job", "123456")
    login.command("submit_code", "job", "123456")
    assert login._commands.get_nowait() == ("submit_code", "123456")
    assert "123456" not in str(login.status())
    with pytest.raises(AcademicError):
        login.command("submit_code", "job", "123456")


def test_send_code_cooldown_and_stop(monkeypatch):
    monkeypatch.setattr(login, "_thread", Running())
    login._state.update(job_id="job", state="waiting_code", resend_after=time.monotonic() + 60)
    with pytest.raises(AcademicError) as error:
        login.command("send_code", "job")
    assert error.value.status == 429
    login.stop()
    assert login._commands.get_nowait()[0] == "stop"
    with pytest.raises(AcademicError):
        login.delete_credentials()


def test_prepare_never_fills_another_origin():
    class Page:
        url = "https://example.com/login"
        def get_by_role(self, *args, **kwargs):
            pytest.fail("must not touch unknown origin")
    assert not login.prepare(Page(), "13800138000")


@pytest.fixture
def school_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


@pytest.mark.parametrize("delay,already_selected", [(0, False), (900, False), (0, True)])
def test_continue_school_login_waits_for_sso_panel(school_page, delay, already_selected):
    page = school_page
    html = f"""<button onclick="setTimeout(() => document.querySelector('#sso').hidden=false, {delay})">统一认证</button>
        <button onclick="window.wrongLogin=true">登录</button>
        <div hidden>统一认证登录</div>
        <button id="sso" {'hidden' if not already_selected else ''}
            onclick="window.ssoClicked=true">统一认证登录</button>"""
    page.route("https://tls.ccsut.cn/**", lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8"))
    page.goto("https://tls.ccsut.cn/admin/login")
    assert login.continue_school_login(page)
    assert page.evaluate("window.ssoClicked === true && !window.wrongLogin")


def test_continue_school_login_does_not_click_other_school_pages(school_page):
    school_page.route("https://tls.ccsut.cn/**", lambda route: route.fulfill(
        body='<button onclick="window.clicked=true">统一认证登录</button>', content_type="text/html; charset=utf-8"))
    school_page.goto("https://tls.ccsut.cn/admin/home")
    assert not login.continue_school_login(school_page)
    assert school_page.evaluate("!window.clicked")


def test_continue_school_login_never_uses_ordinary_login(school_page):
    school_page.route("https://tls.ccsut.cn/**", lambda route: route.fulfill(
        body='<button onclick="window.clicked=true">登录</button>', content_type="text/html; charset=utf-8"))
    school_page.goto("https://tls.ccsut.cn/admin/login")
    assert not login.continue_school_login(school_page)
    assert school_page.evaluate("!window.clicked")


def test_page_error_detects_bridge_captcha_is_wrong():
    class EmptyLocator:
        def all_text_contents(self):
            return []

    class Page:
        def locator(self, sel):
            return EmptyLocator()
        def evaluate(self, expr):
            return "Captcha is wrong."

    assert login.page_error(Page()) == "验证码错误或已过期"



@pytest.mark.parametrize("visible,portal,popup", [(False, False, False), (True, False, False), (False, True, False), (False, False, True)])
def test_login_run_recovers_gateway_and_waits_for_navigation(school_page, monkeypatch, tmp_path, visible, portal, popup):
    from types import SimpleNamespace

    from playwright import sync_api

    page = school_page
    context = page.context
    requests, exported = [], []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    gateway = "https://tls.ccsut.cn/admin/login"
    html = """<meta charset="utf-8"><button onclick="document.querySelector('#sso').hidden=false">统一认证</button>
        <button id="sso" hidden onclick="setTimeout(() => location.href='/admin/home', 1100)">统一认证登录</button>"""

    if popup:
        html = html.replace("location.href='/admin/home'", "window.open('/admin/home', '_blank')")

    def route_school(route):
        requests.append(route.request.url)
        if route.request.url == login.SCHOOL_HOME and portal and requests.count(login.SCHOOL_HOME) == 1:
            route.fulfill(body="<script>location.href='https://zts.ccsut.cn/portal/shortcut.html'</script>", content_type="text/html")
        elif urlsplit(route.request.url).hostname == "zts.ccsut.cn":
            route.fulfill(body="campus portal", content_type="text/html")
        elif route.request.url in (entry, login.SCHOOL_HOME):
            route.fulfill(body="<script>location.href='/admin/login'</script>", content_type="text/html")
        elif route.request.url == gateway:
            route.fulfill(body=html, content_type="text/html; charset=utf-8")
        else:
            route.fulfill(body='<input id="xm"><div class="list_sslct"></div>', content_type="text/html")

    context.route("**/*", route_school)

    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    def export(*args):
        exported.append(args[1].url)
        login._commands.put(("stop", ""))

    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {})
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry, export_verified=export))
    timeout = threading.Timer(8, lambda: login._commands.put(("stop", "")))
    timeout.start()
    try:
        login.run("job", visible=visible)
    finally:
        timeout.cancel()
    assert exported == ["https://tls.ccsut.cn/admin/home"], (requests, login.status())
    assert requests.count(entry) == 0
    assert requests.count(login.SCHOOL_HOME) == (2 if portal else 1)
    assert login.status()["state"] == ("connected" if visible else "stopped")


@pytest.mark.parametrize("account", ["student-id", "1380013800", "138001380000", "23800138000"])
def test_sms_account_requires_phone_number(account):
    with pytest.raises(AcademicError):
        login.save_credentials(account)


def test_prepare_uses_sms_tab_and_form(school_page):
    html = """<meta charset="utf-8">
        <button role="tab" onclick="document.querySelector('#sms').hidden=false">验证码登录</button>
        <form><input formcontrolname="username"><input formcontrolname="password"></form>
        <form id="sms" hidden><input formcontrolname="username"><input formcontrolname="code"></form>"""
    school_page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8"))
    school_page.goto("https://auth.ccsut.cn/backstage/cas/login")
    assert login.prepare(school_page, "13800138000")
    assert login.sms_form(school_page).locator('input[formcontrolname="username"]').input_value() == "13800138000"
    assert school_page.locator('input[formcontrolname="password"]').input_value() == ""


def test_generic_school_rejection_is_reported():
    class Locator:
        def all_text_contents(self):
            return ["Login Failed."]
    class Page:
        def locator(self, selector):
            return Locator()
        def evaluate(self, expression):
            return "Login Failed."
    assert "学校拒绝" in login.page_error(Page())


class SessionContext:
    def __init__(self):
        self.restored = []
    def cookies(self):
        return [{"name": "session", "value": "private-session", "domain": "auth.ccsut.cn", "path": "/", "expires": -1},
                {"name": "other", "value": "unrelated", "domain": "example.com", "path": "/"}]
    def add_cookies(self, cookies):
        self.restored = cookies


def test_session_cookies_survive_stop_and_restart_encrypted():
    old = SessionContext()
    login.save_browser_session(old)
    assert b"private-session" not in login.BROWSER_SESSION.read_bytes()
    restored = SessionContext()
    login.restore_browser_session(restored)
    assert restored.restored == [old.cookies()[0]]
    login.delete_credentials()
    assert not login.BROWSER_SESSION.exists()


def test_changed_key_does_not_restore_session_cookies(monkeypatch):
    monkeypatch.setenv("ACADEMIC_CREDENTIAL_SECRET", "x" * 40)
    context = SessionContext()
    login.save_browser_session(context)
    monkeypatch.setenv("ACADEMIC_CREDENTIAL_SECRET", "different-" + "y" * 40)
    login.restore_browser_session(context)
    assert context.restored == []


def test_portal_redirect_loop_ends_without_reopening_timetable(school_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from playwright import sync_api

    context = school_page.context
    requests = []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    portal = "https://zts.ccsut.cn/portal/shortcut.html"
    def route_school(route):
        requests.append(route.request.url)
        if route.request.url == portal:
            body = "campus portal"
        else:
            body = f"<script>location.href='{portal}'</script>"
        route.fulfill(body=body, content_type="text/html")
    context.route("**/*", route_school)
    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {})
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry))
    timeout = threading.Timer(8, lambda: login._commands.put(("stop", "")))
    timeout.start()
    try:
        login.run("job")
    finally:
        timeout.cancel()
    assert login.status()["state"] == "needs_login"
    assert requests.count(entry) == 0
    assert requests.count(login.SCHOOL_HOME) == 4


@pytest.mark.parametrize("dashboard", ["iframe", "logout"])
def test_home_session_is_validated_through_timetable(school_page, monkeypatch, tmp_path, dashboard):
    from types import SimpleNamespace

    from playwright import sync_api

    context = school_page.context
    requests, exported = [], []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    def route_school(route):
        requests.append(route.request.url)
        home = ('<a href="/admin/caslogout">退出</a>' if dashboard == "logout" else
                '<script>setTimeout(() => { const frame=document.createElement("iframe"); document.body.appendChild(frame); }, 900)</script>')
        body = '<input id="xm"><div class="list_sslct"></div>' if route.request.url == entry else home
        route.fulfill(body=body, content_type="text/html")
    context.route("**/*", route_school)
    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    def export(*args):
        exported.append(args[1].url)
        login._commands.put(("stop", ""))
    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {})
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry, export_verified=export))
    timeout = threading.Timer(8, lambda: login._commands.put(("stop", "")))
    timeout.start()
    try:
        login.run("job")
    finally:
        timeout.cancel()
    assert requests == [login.SCHOOL_HOME, entry]
    assert exported == [entry]


def test_restart_restores_only_enabled_maintenance(monkeypatch):
    starts = []
    monkeypatch.setattr(login, "start", lambda: starts.append(True))
    login.resume()
    assert starts == []
    login.save_maintenance(enabled=True)
    login.resume()
    assert starts == [True]
    login.stop()
    login.resume()
    assert starts == [True]


def test_service_shutdown_preserves_opt_in_but_manual_stop_disables_it():
    login.save_maintenance(enabled=True, last_verified_at="2026-10-09T14:00:00+00:00")
    login.shutdown()
    assert login.status()["maintenance_enabled"]
    assert login.status()["last_verified_at"] == "2026-10-09T14:00:00+00:00"
    login.stop()
    assert not login.status()["maintenance_enabled"]


def test_transient_failures_back_off_and_stop_interrupts_retry(monkeypatch):
    delays = []
    states = []
    class StopEvent:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, delay):
            delays.append(delay)
            states.append(login.status()["state"])
            assert login.status()["next_retry_at"]
            self.stopped = len(delays) == 6
            return self.stopped
    monkeypatch.setattr(login, "_stop_event", StopEvent())
    monkeypatch.setattr(login, "run", lambda *a, **kw: login.update("error", "网络超时", error_type="TimeoutError"))
    login.supervise("job")
    assert delays == [30, 60, 120, 240, 300, 300]
    assert states == ["retrying"] * 6
    assert login.status()["state"] == "stopped"
    assert login.status()["next_retry_at"] is None


def test_human_login_is_not_automatically_retried(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(True)
        login.update("needs_login", "需要验证码")
    monkeypatch.setattr(login, "run", run)
    login.supervise("job")
    assert calls == [True]
    assert login.status()["state"] == "needs_login"


def test_visible_login_hands_off_to_headless_in_same_supervisor(monkeypatch):
    modes = []
    def run(job, visible=False):
        modes.append(visible)
        if visible:
            return "handoff"
        login.update("needs_login", "需要登录")
    monkeypatch.setattr(login, "run", run)
    login.supervise("job", visible=True)
    assert modes == [True, False]


def test_start_does_not_create_second_maintenance_thread(monkeypatch):
    login.save_credentials("13800138000")
    monkeypatch.setattr(login, "_thread", Running())
    monkeypatch.setattr(threading, "Thread", lambda *a, **kw: pytest.fail("must not launch second worker"))
    assert login.start()["running"]


def test_resume_reports_missing_credentials_without_disabling_opt_in():
    login.save_maintenance(enabled=True)
    login.resume()
    assert login.status()["state"] == "needs_login"
    assert login.status()["maintenance_enabled"]


def test_delete_credentials_cancels_restart_recovery():
    login.save_credentials("13800138000")
    login.save_maintenance(enabled=True)
    login.delete_credentials()
    assert not login.status()["maintenance_enabled"]


def test_stalled_school_gateway_recovers_once_then_reports_timeout(school_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from playwright import sync_api
    context = school_page.context
    requests = []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    def route_school(route):
        requests.append(route.request.url)
        route.fulfill(body="<html>Loading...</html>", content_type="text/html")
    context.route("**/*", route_school)
    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {})
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry))
    monkeypatch.setattr(login, "GATEWAY_RECOVERY_SECONDS", 0.1)
    monkeypatch.setattr(login, "GATEWAY_TIMEOUT_SECONDS", 1.2)
    monkeypatch.setattr(login, "capture_login_page", lambda page: None)
    login.run("job")
    assert requests == [login.SCHOOL_HOME, entry]
    assert login.status()["state"] == "error"
    assert login.status()["error_type"] == "gateway_timeout"


def test_gateway_timeout_retries_until_recovered_without_manual_alert(monkeypatch):
    events, delays = [], []
    login.save_maintenance(enabled=True)
    monkeypatch.setattr(login.academic_mail, "connection_event", events.append)
    class StopEvent:
        def is_set(self):
            return False
        def wait(self, delay):
            delays.append(delay)
            return False
    monkeypatch.setattr(login, "_stop_event", StopEvent())
    def run(*args, **kwargs):
        if not delays:
            login.update("error", "页面超时", error_type="gateway_timeout")
        else:
            login.update("connected", "恢复成功")
    monkeypatch.setattr(login, "run", run)
    login.supervise("job")
    assert delays == [30]
    assert events == ["maintenance_error", "connected"]


def test_persistent_maintenance_failure_creates_one_monitoring_incident(monkeypatch):
    events = []
    login.save_maintenance(enabled=True)
    monkeypatch.setattr(login.academic_mail, "connection_event", events.append)
    login.update("retrying", "重试", retry_attempt=5)
    assert events == []
    login.update("retrying", "重试", retry_attempt=6)
    assert events == ["maintenance_error"]

def test_course_selection_redirect_navigates_to_timetable(school_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from playwright import sync_api

    context = school_page.context
    requests, exported = [], []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    xk_page = "https://tls.ccsut.cn/frontend/views/student/xkPage/index.html"

    def route_school(route):
        requests.append(route.request.url)
        if route.request.url == login.SCHOOL_HOME:
            route.fulfill(body=f"<script>location.href='{xk_page}'</script>", content_type="text/html")
        elif route.request.url == xk_page:
            route.fulfill(body="<html><body>选课列表</body></html>", content_type="text/html; charset=utf-8")
        else:
            route.fulfill(body='<input id="xm"><div class="list_sslct"></div>', content_type="text/html")

    context.route("**/*", route_school)

    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    def export(*args):
        exported.append(args[1].url)
        login._commands.put(("stop", ""))

    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {})
    monkeypatch.setattr(login, "LANDING_SETTLE_SECONDS", 0.1)
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry, export_verified=export))
    timeout = threading.Timer(8, lambda: login._commands.put(("stop", "")))
    timeout.start()
    try:
        login.run("job")
    finally:
        timeout.cancel()
    assert requests == [login.SCHOOL_HOME, xk_page, entry]
    assert exported == [entry]


def test_intercepted_timetable_falls_back_to_http_verification(school_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from playwright import sync_api

    context = school_page.context
    context.add_cookies([{"name": "username", "value": "13800138000", "domain": "tls.ccsut.cn", "path": "/"}])
    requests, exported = [], []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    xk_page = "https://tls.ccsut.cn/frontend/views/student/xkPage/index.html"

    def route_school(route):
        requests.append(route.request.url)
        if route.request.url in (login.SCHOOL_HOME, entry):
            route.fulfill(body=f"<script>location.href='{xk_page}'</script>", content_type="text/html")
        else:
            route.fulfill(body="<html><body>强制选课/评教页面</body></html>", content_type="text/html; charset=utf-8")

    context.route("**/*", route_school)

    class Engine:
        chromium = SimpleNamespace(launch_persistent_context=lambda *args, **kwargs: context)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    def export(*args):
        exported.append(args[1].url)
        login._commands.put(("stop", ""))

    monkeypatch.setattr(sync_api, "sync_playwright", Engine)
    monkeypatch.setattr(login, "PROFILE", tmp_path / "managed-browser-profile")
    monkeypatch.setattr(login, "credentials", lambda: {"account": "13800138000"})
    monkeypatch.setattr(login, "LANDING_SETTLE_SECONDS", 0.05)
    monkeypatch.setattr(login, "school_module", lambda: SimpleNamespace(ENTRY=entry, export_verified=export))
    timeout = threading.Timer(8, lambda: login._commands.put(("stop", "")))
    timeout.start()
    try:
        login.run("job")
    finally:
        timeout.cancel()
    assert exported == [xk_page]
    assert requests.count(entry) == login.MAX_TIMETABLE_REDIRECTS



def test_changing_phone_clears_all_previous_session_state(monkeypatch):
    login.save_credentials("13800138000")
    login.BROWSER_SESSION.write_bytes(b"old-session")
    login.PROFILE.mkdir()
    (login.PROFILE / "cookies").write_text("old-cookies")
    from app.services import academic
    academic.CONFIG_FILE.write_bytes(b"old-connection")
    login.save_credentials("13900139000")
    assert not login.BROWSER_SESSION.exists()
    assert not login.PROFILE.exists()
    assert not academic.CONFIG_FILE.exists()
    assert login.credentials()["account"] == "13900139000"
    monkeypatch.setenv("CCSUT_COOKIE", "username=old-account")
    with pytest.raises(AcademicError):
        academic.connection_headers()
    academic.save_connection("username=new-account", "test-agent")
    assert academic.connection_headers()["Cookie"] == "username=new-account"


def test_deleting_phone_also_clears_browser_profile():
    login.save_credentials("13800138000")
    login.PROFILE.mkdir()
    (login.PROFILE / "cookies").write_text("old-cookies")
    login.delete_credentials()
    assert not login.PROFILE.exists()


def test_changing_phone_clears_persisted_and_visible_verified_time():
    login.save_credentials("13800138000")
    login.save_maintenance(last_verified_at="2026-10-01T00:00:00+00:00")
    login._state["last_verified_at"] = "2026-10-01T00:00:00+00:00"
    login.save_credentials("13900139000")
    assert login.maintenance_settings().get("last_verified_at") is None
    assert login.status()["last_verified_at"] is None
