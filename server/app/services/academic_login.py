"""Administrator-controlled normal school login in a dedicated browser thread."""
import importlib.util
import json
import logging
import os
import queue
import re
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from Crypto.Cipher import AES

from . import academic_mail
from .academic import ROOT, AcademicError, _key

DIRECTORY = ROOT / "data" / "academic"
CREDENTIALS = DIRECTORY / "credentials.enc"
PROFILE = DIRECTORY / "managed-browser-profile"
BROWSER_SESSION = DIRECTORY / "browser-session.enc"
MAINTENANCE = DIRECTORY / "maintenance.json"
SCHOOL_LOGIN = "https://tls.ccsut.cn/admin/login"
SCHOOL_HOME = "https://tls.ccsut.cn/admin/?loginType=1"
GATEWAY_RECOVERY_SECONDS = 20
GATEWAY_TIMEOUT_SECONDS = 60
LANDING_SETTLE_SECONDS = 3
MAX_TIMETABLE_REDIRECTS = 2
_lock = threading.RLock()
_commands = queue.Queue(maxsize=8)
_thread = None
_stop_event = threading.Event()
_state = {"state": "not_started", "message": "尚未启动学校登录"}


def maintenance_settings():
    try:
        data = json.loads(MAINTENANCE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_maintenance(**changes):
    with _lock:
        data = maintenance_settings()
        data.update(changes)
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        temporary = MAINTENANCE.with_name("maintenance-" + secrets.token_hex(8) + ".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(MAINTENANCE)


def retry_delay(attempt):
    return min(300, 30 * 2 ** min(max(attempt - 1, 0), 4))


def supervise(job, visible=False):
    attempt = 0
    while not _stop_event.is_set():
        outcome = run(job, visible=visible)
        if _stop_event.is_set():
            break
        if outcome == "handoff":
            visible = False
            update("recovering", "人工登录已验证，正在交接后台维护", visible=False)
            continue
        if status()["state"] != "error":
            break
        with _lock:
            if _state.pop("verified_this_attempt", False):
                attempt = 0
        attempt += 1
        delay = retry_delay(attempt)
        update("retrying", f"会话维护异常，{delay} 秒后自动重试", retry_attempt=attempt,
               next_retry_at=(datetime.now(UTC) + timedelta(seconds=delay)).isoformat(), visible=False)
        if _stop_event.wait(delay):
            break
        visible = False
        update("recovering", "正在恢复学校浏览器会话", next_retry_at=None, diagnostic=False)
    if _stop_event.is_set():
        update("stopped", "已停止学校登录维护", next_retry_at=None, visible=False)


def resume():
    if maintenance_settings().get("enabled") is not True:
        return
    try:
        start()
    except AcademicError as error:
        update("needs_login", "无法自动恢复，请检查浏览器依赖和学校手机号后重新发起维护",
               error_type=error.code)


def shutdown():
    stop(preserve_enabled=True)
    thread = _thread
    if thread and thread.is_alive():
        thread.join(timeout=60)


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
        previous = _state.get("state")
        _state.update(state=state, message=message, checked_at=datetime.now(UTC).isoformat(), **details)
    if previous != state:
        logging.getLogger(__name__).info("School maintenance state: %s -> %s (%s)", previous, state, details.get("error_type", ""))
    try:
        settings = maintenance_settings()
        if state == "connected":
            academic_mail.connection_event("connected")
        elif state == "stopped" and not settings.get("enabled"):
            academic_mail.connection_event("stopped")
        elif settings.get("enabled") and ((state == "error" and details.get("error_type") == "gateway_timeout")
                or (state == "retrying" and details.get("retry_attempt", 0) >= 6)):
            academic_mail.connection_event("maintenance_error")
        elif settings.get("enabled") and (state == "needs_login" or
                state in {"ready_for_code", "waiting_code"} and settings.get("last_verified_at")):
            academic_mail.connection_event("needs_login")
    except Exception as error:
        logging.getLogger(__name__).warning("School mail event unavailable: %s", type(error).__name__)


def status():
    with _lock:
        result = dict(_state)
        result["saved"] = CREDENTIALS.exists()
        result["running"] = bool(_thread and _thread.is_alive())
        settings = maintenance_settings()
        result["maintenance_enabled"] = settings.get("enabled") is True
        result["last_verified_at"] = _state.get("last_verified_at") or settings.get("last_verified_at")
    if result["saved"]:
        try:
            result["account"] = credentials()["account"]
        except AcademicError:
            result["message"] = "已保存凭据无法解密，请重新保存"
    result["available"] = importlib.util.find_spec("playwright") is not None
    return result


def start(visible: bool = False):
    global _thread, _commands, _stop_event
    if not visible:
        credentials()
    with _lock:
        if _thread and _thread.is_alive():
            return status()
        if importlib.util.find_spec("playwright") is None:
            raise AcademicError("browser_unavailable", "请安装学校浏览器依赖和 Chromium", 503)
        _commands = queue.Queue(maxsize=8)
        _stop_event = threading.Event()
        save_maintenance(enabled=True)
        job = secrets.token_urlsafe(18)
        _state.clear()
        msg = "已打开可视浏览器，请在弹出的窗口中登录…" if visible else "正在打开学校登录页面"
        _state.update(state="starting", message=msg, job_id=job, visible=visible)
        _thread = threading.Thread(target=supervise, args=(job, visible), daemon=True, name="academic-login")
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
        else:
            save_maintenance(enabled=False)
            _stop_event.set()
        try:
            _commands.put_nowait((action, code.strip()))
        except queue.Full as error:
            raise AcademicError("login_busy", "操作繁忙，请稍后重试", 429) from error
    return status()


def stop(preserve_enabled=False):
    if not preserve_enabled:
        save_maintenance(enabled=False)
    _stop_event.set()
    current = status()
    if current["running"]:
        try:
            _commands.put_nowait(("stop", ""))
        except queue.Full:
            pass
    else:
        update("stopped", "已停止学校登录维护", next_retry_at=None, visible=False)


def delete_credentials():
    if status()["running"]:
        raise AcademicError("login_running", "请先停止登录维护，再删除凭据", 409)
    CREDENTIALS.unlink(missing_ok=True)
    BROWSER_SESSION.unlink(missing_ok=True)
    save_maintenance(enabled=False, last_verified_at=None)
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


def _has_school_account_cookie(context, worker):
    try:
        cookies = context.cookies([worker.ENTRY])
        return any(item.get("name") == "username" and item.get("value") for item in cookies)
    except Exception:
        return False


def _verify_and_mark_connected(context, page, worker, account):
    worker.export_verified(context, page, account)
    save_browser_session(context)
    verified_at = datetime.now(UTC).isoformat()
    save_maintenance(last_verified_at=verified_at)
    update("connected", "学校已连接，自动维护运行中", visible=False,
           last_verified_at=verified_at, next_retry_at=None, retry_attempt=0,
           error_type=None, diagnostic=False, verified_this_attempt=True)


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
                gateway_since, gateway_recovered = None, False
                landing_path, landing_since = None, None
                timetable_redirects = 0
                if visible:
                    update("manual_waiting", "已在桌面弹出浏览器窗口，请在窗口中登录（支持密码/验证码/微信扫码）", visible=True)
                while True:
                    if _stop_event.is_set():
                        update("stopped", "已停止学校登录维护")
                        break
                    school_pages = [candidate for candidate in context.pages if not candidate.is_closed()
                                    and urlsplit(candidate.url).hostname in {"auth.ccsut.cn", "zts.ccsut.cn", "tls.ccsut.cn"}]
                    if school_pages:
                        page = school_pages[-1]
                    if page.is_closed():
                        update("needs_login" if visible else "error",
                               "登录窗口已关闭，请重新登录" if visible else "维护浏览器已关闭，等待自动恢复", visible=False)
                        break
                    page.wait_for_timeout(200 if visible else 100)
                    if ready and time.monotonic() >= next_check:
                        update("checking", "正在检查学校会话")
                        ready = False
                        deadline = time.monotonic() + 600
                        timetable_redirects = 0
                        landing_path, landing_since = None, None
                        page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                    location = urlsplit(page.url)
                    current_path = location.path.rstrip("/") or "/"
                    if location.hostname != "tls.ccsut.cn" or ready:
                        gateway_since, gateway_recovered = None, False
                        landing_path, landing_since = None, None
                        if location.hostname != "tls.ccsut.cn":
                            timetable_redirects = 0
                    with _lock:
                        _state.update(page_host=location.hostname, page_path=current_path)
                    if (location.hostname == "tls.ccsut.cn" and page.locator("#xm").count()
                            and page.locator(".list_sslct").count()):
                        if not ready or time.monotonic() >= next_check:
                            _verify_and_mark_connected(context, page, worker, saved.get("account", ""))
                            portal_attempts = 0
                            timetable_redirects = 0
                            ready, next_check = True, time.monotonic() + 600
                            if visible:
                                page.wait_for_timeout(2000)
                                return "handoff"
                    elif location.hostname == "zts.ccsut.cn" and location.path == "/portal/shortcut.html":
                        # This entry finalizes/reuses the school session; the timetable
                        # and ordinary login URLs can both bounce back to the campus portal.
                        # Allow the portal's asynchronous SSO redirect to finish.
                        page.wait_for_timeout(1500)
                        if urlsplit(page.url).hostname != 'zts.ccsut.cn':
                            continue
                        portal_attempts += 1
                        if portal_attempts > 3:
                            update("needs_login", "学校门户与教务系统跳转未完成，请重新启动维护并完成验证码登录")
                            break
                        update("continuing", "正在恢复教务系统会话")
                        page.goto(SCHOOL_HOME, wait_until="domcontentloaded", timeout=45000)
                    elif location.hostname == "tls.ccsut.cn":
                        now = time.monotonic()
                        if gateway_since is None:
                            gateway_since = now
                        if current_path != landing_path:
                            landing_path, landing_since = current_path, now
                        entry_path = urlsplit(worker.ENTRY).path.rstrip("/")
                        if not visible and now - gateway_since >= GATEWAY_TIMEOUT_SECONDS:
                            if _has_school_account_cookie(context, worker) and hasattr(worker, "export_verified"):
                                try:
                                    _verify_and_mark_connected(context, page, worker, saved.get("account", ""))
                                    portal_attempts = 0
                                    timetable_redirects = 0
                                    ready, next_check = True, time.monotonic() + 600
                                    continue
                                except (AcademicError, ValueError):
                                    raise
                                except Exception:
                                    pass
                            capture_login_page(page)
                            error_type = "gateway_timeout" if current_path in {"/admin", "/admin/login", entry_path} else "unexpected_landing"
                            update("error", f"教务系统页面加载超时（{current_path}），正在等待自动恢复；尚未确认查询连接失效",
                                   diagnostic=True, error_type=error_type, page_path=current_path)
                            break
                        if (not visible and not gateway_recovered and current_path == "/admin"
                                and now - gateway_since >= GATEWAY_RECOVERY_SECONDS):
                            gateway_recovered = True
                            update("continuing", "教务系统首页加载较慢，正在尝试直接验证课表连接")
                            page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=30000)
                            continue
                        # Handle the school gateway in every phase, including profile recovery.
                        if current_path == "/admin":
                            # The gateway initially renders a loading document. Wait for the
                            # authenticated dashboard marker before navigating away from it.
                            if (page.locator("iframe").count()
                                    or page.locator('a[href*="/admin/caslogout"]').count()):
                                update("checking", "已进入教务系统，正在验证课表连接")
                                page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                                continued = 0
                        elif current_path == "/admin/login":
                            if not continued or time.monotonic() - continued >= 10:
                                if continue_school_login(page):
                                    continued = time.monotonic()
                                    update("continuing", "正在通过统一认证进入教务系统")
                        elif continued and time.monotonic() - continued >= 3:
                            # Leave the login page's navigation alone until it reaches the school.
                            page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                            continued = 0
                        elif current_path != entry_path and now - landing_since >= LANDING_SETTLE_SECONDS:
                            if timetable_redirects < MAX_TIMETABLE_REDIRECTS:
                                timetable_redirects += 1
                                landing_since = now
                                update("checking", "已进入教务系统，正在跳转课表页面验证连接")
                                page.goto(worker.ENTRY, wait_until="domcontentloaded", timeout=45000)
                            elif _has_school_account_cookie(context, worker) and hasattr(worker, "export_verified"):
                                _verify_and_mark_connected(context, page, worker, saved.get("account", ""))
                                portal_attempts = 0
                                timetable_redirects = 0
                                ready, next_check = True, time.monotonic() + 600
                                if visible:
                                    page.wait_for_timeout(2000)
                                    return "handoff"
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
                    elif status()["state"] in ("starting", "checking", "recovering"):
                        if saved.get("account") and prepare(page, saved["account"]):
                            if not visible:
                                update("ready_for_code", "手机号已填入，请点击获取验证码")
                        elif time.monotonic() > deadline:
                            update("needs_login", "学校登录页面未能自动处理，请使用高级连接或稍后重试")
                            break
                    if (not ready and status()["state"] not in ("submitting", "continuing")
                            and time.monotonic() > deadline):
                        update("needs_login", "需要人工完成学校登录，请重新发起登录", visible=False)
                        break
                    try:
                        action, code = _commands.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if action == "stop":
                        update("stopped", "已停止学校登录维护")
                        break
                    # Commands queued before successful verification are now obsolete.
                    if ready or status()["state"] in ("submitting", "continuing"):
                        continue
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
    except AcademicError as error:
        if error.code in {"connection_expired", "connection_missing", "permission_denied"}:
            update("needs_login", "学校要求重新登录或无查询权限，请管理员完成登录", error_type=error.code)
        else:
            update("error", "学校连接验证失败，等待自动重试", error_type=type(error).__name__)
    except ValueError as error:
        if str(error) == "account_mismatch":
            update("needs_login", "学校登录账号不匹配，请管理员重新登录", error_type="account_mismatch")
        else:
            update("error", "会话验证失败，等待自动重试", error_type=type(error).__name__)
    except Exception as error:
        if visible and type(error).__name__ == "TargetClosedError":
            update("needs_login", "登录窗口已关闭，请重新发起登录", visible=False)
        else:
            update("error", "登录维护异常，等待自动恢复", error_type=type(error).__name__)
    finally:
        while True:
            try:
                _commands.get_nowait()
            except queue.Empty:
                break
