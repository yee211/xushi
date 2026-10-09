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
    monkeypatch.setattr(login, "CREDENTIALS", tmp_path / "credentials.enc")
    monkeypatch.setattr(login, "BROWSER_SESSION", tmp_path / "browser-session.enc")
    monkeypatch.setattr(login, "_thread", None)
    monkeypatch.setattr(login, "_commands", queue.Queue(maxsize=8))
    monkeypatch.setattr(login, "_state", {"state": "not_started", "message": "test"})


def test_credentials_are_encrypted_and_never_return_password():
    login.save_credentials("13800138000")
    assert b"13800138000" not in login.CREDENTIALS.read_bytes()
    assert login.credentials() == {"account": "13800138000"}
    result = login.status()
    assert result["account"] == "13800138000"
    assert "password" not in result
    login.delete_credentials()
    assert not login.status()["saved"]


def test_changed_key_fails_closed(monkeypatch):
    login.save_credentials("13800138000")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "different-" + "y" * 40)
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
    monkeypatch.setattr(login, "PROFILE", tmp_path / "profile")
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
    context = SessionContext()
    login.save_browser_session(context)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "different-" + "y" * 40)
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
    monkeypatch.setattr(login, "PROFILE", tmp_path / "profile")
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


def test_home_session_is_validated_through_timetable(school_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from playwright import sync_api

    context = school_page.context
    requests, exported = [], []
    entry = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
    def route_school(route):
        requests.append(route.request.url)
        body = '<input id="xm"><div class="list_sslct"></div>' if route.request.url == entry else '<script>setTimeout(() => { const frame=document.createElement("iframe"); document.body.appendChild(frame); }, 900)</script>'
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
    monkeypatch.setattr(login, "PROFILE", tmp_path / "profile")
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
