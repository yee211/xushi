"""Administrator-controlled normal school login in a dedicated browser thread."""
import importlib.util
import json
import os
import queue
import re
import secrets
import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from Crypto.Cipher import AES

from .academic import ROOT, AcademicError, _key

DIRECTORY = ROOT / "data" / "academic"
CREDENTIALS = DIRECTORY / "credentials.enc"
PROFILE = DIRECTORY / "managed-browser-profile"
BROWSER_SESSION = DIRECTORY / "browser-session.enc"
SCHOOL_LOGIN = "https://tls.ccsut.cn/admin/login"
SCHOOL_HOME = "https://tls.ccsut.cn/admin/?loginType=1"
_lock = threading.RLock()
_commands = queue.Queue(maxsize=8)
_thread = None
_state = {"state": "not_started", "message": "尚未启动学校登录"}


def save_credentials(account):
    account = account.strip()
    if not re.fullmatch(r"1[0-9]{10}", account):
        raise AcademicError("credentials_invalid", "请输入学校绑定的 11 位手机号", 422)
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=os.urandom(12))
    raw, tag = cipher.encrypt_and_digest(json.dumps({"account": account}).encode())
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = CREDENTIALS.with_name("credentials-" + secrets.token_hex(8) + ".tmp")
    temporary.write_bytes(cipher.nonce + tag + raw)
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(CREDENTIALS)


def credentials():
    try:
        raw = CREDENTIALS.read_bytes()
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=raw[:12])
        saved = json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
        return {"account": saved["account"]}
    except Exception as error:
        raise AcademicError("credentials_unavailable", "请保存学校手机号；密钥变更后需重新保存", 503) from error



def save_browser_session(context):
    # Chromium does not retain session cookies when the browser closes.
    cookies = [cookie for cookie in context.cookies()
               if cookie["domain"].lstrip(".") == "ccsut.cn"
               or cookie["domain"].lstrip(".").endswith(".ccsut.cn")]
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=os.urandom(12))
    raw, tag = cipher.encrypt_and_digest(json.dumps(cookies).encode())
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = BROWSER_SESSION.with_name("browser-session-" + secrets.token_hex(8) + ".tmp")
    temporary.write_bytes(cipher.nonce + tag + raw)
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(BROWSER_SESSION)


def restore_browser_session(context):
    if not BROWSER_SESSION.exists():
        return
    try:
        raw = BROWSER_SESSION.read_bytes()
        cipher = AES.new(_key(), AES.MODE_GCM, nonce=raw[:12])
        cookies = json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
        context.add_cookies(cookies)
    except Exception:
        # Expired or undecryptable state falls back to the normal SMS login.
        return

def update(state, message, **details):
    with _lock:
        _state.update(state=state, message=message, checked_at=datetime.now(UTC).isoformat(), **details)


def status():
    with _lock:
        result = dict(_state)
        result["saved"] = CREDENTIALS.exists()
        result["running"] = bool(_thread and _thread.is_alive())
    if result["saved"]:
        try:
            result["account"] = credentials()["account"]
        except AcademicError:
            result["message"] = "已保存凭据无法解密，请重新保存"
    result["available"] = importlib.util.find_spec("playwright") is not None
    return result


def start(visible: bool = False):
    global _thread, _commands
    if not visible:
        credentials()
    with _lock:
        if _thread and _thread.is_alive():
            return status()
        if importlib.util.find_spec("playwright") is None:
            raise AcademicError("browser_unavailable", "请安装学校浏览器依赖和 Chromium", 503)
        _commands = queue.Queue(maxsize=8)
        job = secrets.token_urlsafe(18)
        _state.clear()
        msg = "已打开可视浏览器，请在弹出的窗口中登录…" if visible else "正在打开学校登录页面"
        _state.update(state="starting", message=msg, job_id=job, visible=visible)
        _thread = threading.Thread(target=run, args=(job, visible), daemon=True, name="academic-login")
        _thread.start()
    return status()


def command(action, job_id, code=""):
    with _lock:
        if not _thread or not _thread.is_alive() or job_id != _state.get("job_id"):
            raise AcademicError("login_not_running", "登录过程已结束，请重新发起登录", 409)
        allowed = {"send_code": {"ready_for_code", "waiting_code"}, "submit_code": {"waiting_code"}, "stop": set()}
        if action != "stop" and _state.get("state") not in allowed.get(action, set()):
            raise AcademicError("login_step_invalid", "当前登录步骤不允许此操作", 409)
        if action == "submit_code" and (not code.strip() or len(code) > 32):
            raise AcademicError("code_invalid", "请输入收到的验证码", 422)
        if action == "send_code" and time.monotonic() < _state.get("resend_after", 0):
            raise AcademicError("code_rate_limited", "验证码发送间隔为 60 秒，请稍后重试", 429)
        if action != "stop":
            _state.update(state="processing", message="正在处理登录操作")
        try:
            _commands.put_nowait((action, code.strip()))
        except queue.Full as error:
            raise AcademicError("login_busy", "操作繁忙，请稍后重试", 429) from error
    return status()


def stop():
    current = status()
    if current["running"]:
        command("stop", current["job_id"])


def delete_credentials():
    if status()["running"]:
        raise AcademicError("login_running", "请先停止登录维护，再删除凭据", 409)
    CREDENTIALS.unlink(missing_ok=True)
    BROWSER_SESSION.unlink(missing_ok=True)
    update("not_started", "学校手机号已删除")


def school_module():
    spec = importlib.util.spec_from_file_location("academic_session_worker", ROOT / "scripts" / "academic_session_worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sms_form(page):
    return page.locator("form").filter(has=page.locator('input[formcontrolname="code"]')).filter(visible=True)


def prepare(page, account):
    if urlsplit(page.url).hostname != "auth.ccsut.cn":
        return False
    tab = page.get_by_role("tab", name="验证码登录", exact=True)
    if not tab.count():
        return False
    tab.click()
    form = sms_form(page)
    form.locator('input[formcontrolname="username"]').fill(account)
    return True


def page_error(page):
    messages = page.locator('[role="alert"],.ant-message-notice-content,.ant-form-item-explain-error,.el-message__content,.ivu-message-notice-content,.ivu-form-item-error-tip,.error').all_text_contents()
    text = "；".join(messages)
    try:
        bridge_errors = page.evaluate("() => (window.bridgeData && window.bridgeData.errors) ? window.bridgeData.errors.join('；') : ''")
        if bridge_errors:
            text = text + "；" + bridge_errors
    except Exception:
        pass
    for label in ("验证码错误", "验证码已过期", "验证码过期", "密码错误", "账号或密码错误", "验证码不能为空",
                  "用户名或密码错误", "账号不存在", "验证码不正确", "请先获取验证码", "请拖动", "安全验证",
                  "Captcha is wrong", "Username or Password is invalid", "Login Failed"):
        if label.lower() in text.lower():
            if "captcha" in label.lower():
                return "验证码错误或已过期"
            if "password" in label.lower() or "username" in label.lower():
                return "账号或密码错误"
            if label == "Login Failed":
                return "学校拒绝了本次登录，请重新获取验证码后重试"
            return label
    return ""


def capture_login_page(page):
    # Hide every input and QR image before capture; no password/code enters the image.
    screenshot = DIRECTORY / "login-page.png"
    style = page.add_style_tag(content="input,textarea,img,canvas { visibility: hidden !important; }")
    try:
        page.screenshot(path=str(screenshot), full_page=False)
        if os.name != "nt":
            screenshot.chmod(0o600)
    finally:
        style.evaluate("el => el.remove()")



def continue_school_login(page):
    location = urlsplit(page.url)
    if location.hostname != "tls.ccsut.cn" or location.path.rstrip("/") != "/admin/login":
        return False
    # Only use SSO: the account-login form does not accept the SSO session.
    button = page.get_by_text("统一认证登录", exact=True).filter(visible=True)
    if not button.count():
        tab = page.get_by_text("统一认证", exact=True).filter(visible=True)
        if not tab.count():
            return False
        tab.first.click(timeout=5000)
    # The panel may render asynchronously; never fall back to ordinary login.
    button.first.wait_for(state="visible", timeout=10000)
    button.first.click(timeout=5000)
    return True


def run(job, visible=False):
    try:
        from playwright.sync_api import sync_playwright
        worker = school_module()
        saved = {}
        try:
            saved = credentials()
        except AcademicError:
            pass
        PROFILE.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            PROFILE.chmod(0o700)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(PROFILE),
                headless=not visible,
                args=["--start-maximized"] if visible else [],
            )
            context.set_default_timeout(15000)
            restore_browser_session(context)
            page = context.pages[0] if context.pages else context.new_page()
            if visible:
                try:
                    page.bring_to_front()
                except Exception:
                    pass
            try:
                page.goto(SCHOOL_HOME, wait_until="domcontentloaded", timeout=45000)
                deadline = time.monotonic() + (900 if visible else 600)
                next_check, ready = 0, False
                submit_deadline, continued = 0, 0
                submitted = False
                portal_attempts = 0
                if visible:
                    update("manual_waiting", "已在桌面弹出浏览器窗口，请在窗口中登录（支持密码/验证码/微信扫码）", visible=True)
                while True:
                    school_pages = [candidate for candidate in context.pages if not candidate.is_closed()
                                    and urlsplit(candidate.url).hostname in {"auth.ccsut.cn", "zts.ccsut.cn", "tls.ccsut.cn"}]
                    if school_pages:
                        page = school_pages[-1]
                    if page.is_closed():
                        update("stopped", "可视浏览器窗口已关闭", visible=False)
                        break
                    page.wait_for_timeout(200 if visible else 100)
                    if ready and time.monotonic() >= next_check:
                        update("checking", "正在检查学校会话")
                        ready = False
                        deadline = time.monotonic() + 600
                        page.goto(SCHOOL_HOME, wait_until="domcontentloaded", timeout=45000)
                    location = urlsplit(page.url)
                    with _lock:
                        _state.update(page_host=location.hostname)
                    if (location.hostname == "tls.ccsut.cn" and page.locator("#xm").count()
                            and page.locator(".list_sslct").count()):
                        if not ready or time.monotonic() >= next_check:
                            worker.export_verified(context, page, saved.get("account", ""))
                            save_browser_session(context)
                            portal_attempts = 0
                            update("connected", "学校已连接，自动维护运行中", visible=False)
                            ready, next_check = True, time.monotonic() + 600
                            if visible:
                                page.wait_for_timeout(2000)
                                break
                    elif location.hostname == "zts.ccsut.cn" and location.path == "/portal/shortcut.html":
                        # This entry finalizes/reuses the school session; the timetable
                        # and ordinary login URLs can both bounce back to the campus portal.
                        # Allow the portal's asynchronous SSO redirect to finish.
                        page.wait_for_timeout(1500)
                        if urlsplit(page.url).hostname != 'zts.ccsut.cn':
                            continue
                        portal_attempts += 1
                        if portal_attempts > 3:
                            update("needs_login", "学校门户与教务系统跳转未完成，请重新登录或使用可视浏览器")
                            break
                        update("continuing", "正在恢复教务系统会话")
                        page.goto(SCHOOL_HOME, wait_until="domcontentloaded", timeout=45000)
                    elif location.hostname == "tls.ccsut.cn":
                        # Handle the school gateway in every phase, including profile recovery.
                        if location.path.rstrip("/") == "/admin":
                            # The gateway initially renders a loading document. Wait for the
                            # authenticated dashboard frame before navigating away from it.
                            if page.locator("iframe").count():
                                save_browser_session(context)
                                update("checking", "已进入教务系统，正在验证课表连接")
                                page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                                continued = 0
                        elif location.path.rstrip("/") == "/admin/login":
                            if not continued or time.monotonic() - continued >= 10:
                                if continue_school_login(page):
                                    continued = time.monotonic()
                                    update("continuing", "正在通过统一认证进入教务系统")
                        elif continued and time.monotonic() - continued >= 3:
                            # Leave the login page's navigation alone until it reaches the school.
                            page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                            continued = 0
                    elif status()["state"] in ("submitting", "continuing", "manual_waiting"):
                        error = page_error(page)
                        if (not visible and not submitted and location.hostname == "auth.ccsut.cn"
                                and saved.get("account") and prepare(page, saved["account"])):
                            update("ready_for_code", "手机号已填入，请点击获取验证码")
                        elif error and location.hostname == "auth.ccsut.cn" and not visible:
                            prepare(page, saved["account"])
                            capture_login_page(page)
                            submitted = False
                            update("ready_for_code", "学校提示：" + error, diagnostic=True)
                        elif not visible and time.monotonic() > submit_deadline:
                            if location.hostname == "auth.ccsut.cn":
                                capture_login_page(page)
                                update("waiting_code", "学校尚未完成登录，请查看下方学校页面提示；未确认验证码错误", diagnostic=True)
                            else:
                                update("needs_login", "登录停留在中间页面，请反馈当前页面域名")
                                break
                    elif status()["state"] in ("starting", "checking"):
                        if saved.get("account") and prepare(page, saved["account"]):
                            if not visible:
                                update("ready_for_code", "手机号已填入，请点击获取验证码")
                        elif time.monotonic() > deadline:
                            update("needs_login", "学校登录页面未能自动处理，请使用高级连接或稍后重试")
                            break
                    if not ready and time.monotonic() > deadline:
                        update("expired", "本次登录等待已超时，请重新发起登录")
                        break
                    try:
                        action, code = _commands.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if action == "stop":
                        update("stopped", "已停止学校登录维护")
                        break
                    if not visible and urlsplit(page.url).hostname != "auth.ccsut.cn":
                        update("needs_login", "学校登录步骤已变化，请重新发起登录")
                        break
                    if action == "send_code":
                        prepare(page, saved["account"])
                        sms_form(page).get_by_role("button", name="获取验证码", exact=True).click()
                        page.wait_for_timeout(800)
                        capture_login_page(page)
                        update("waiting_code", "验证码已请求，请查看学校绑定手机并输入验证码", resend_after=time.monotonic() + 60, diagnostic=True)
                    elif action == "submit_code":
                        sms_form(page).locator('input[formcontrolname="code"]').fill(code)
                        submitted = True
                        submit_deadline, continued = time.monotonic() + 45, 0
                        update("submitting", "正在验证登录并等待进入教务系统，请勿重复提交")
                        sms_form(page).get_by_role("button", name="登录", exact=True).click()
                        page.wait_for_timeout(800)
                        if urlsplit(page.url).hostname == "auth.ccsut.cn":
                            capture_login_page(page)
                            with _lock:
                                _state["diagnostic"] = True
                        code = ""
            finally:
                context.close()
    except Exception as error:
        update("error", "登录维护失败，请检查浏览器依赖或重新发起登录", error_type=type(error).__name__)
    finally:
        while True:
            try:
                _commands.get_nowait()
            except queue.Empty:
                break
