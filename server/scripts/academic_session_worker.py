"""Maintain an authorized CCSUT browser session using normal SSO navigation.

Run on the API host with the same environment and data mount. Never prints cookies.
Optional dependency: playwright; install its Chromium separately.
"""
import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.academic import ROOT, CcsutClient, connection_headers, save_connection

ENTRY = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"
PROFILE = ROOT / "data" / "academic" / "browser-profile"
STATUS = ROOT / "data" / "academic" / "browser-status.json"


def publish(state, **details):
    data = {"state": state, "checked_at": datetime.now(UTC).isoformat(), **details}
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(STATUS)
    print(json.dumps(data, ensure_ascii=False), flush=True)


def wait_for_school(page, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if (urlsplit(page.url).hostname == "tls.ccsut.cn"
                    and page.locator("#xm").count()
                    and page.locator(".list_sslct").count()):
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def export_verified(context, page, expected_account):
    cookies = context.cookies([ENTRY])
    values = {item["name"]: item["value"] for item in cookies}
    # The observed school session exposes the logged-in account as a cookie.
    # This guard is operational account selection, not user identity authentication.
    username = values.get("username")
    if not username:
        raise ValueError("account_mismatch")
    if expected_account and username != expected_account:
        if not (len(expected_account) == 11 and expected_account.isdigit()):
            raise ValueError("account_mismatch")
    cookie = "; ".join(item["name"] + "=" + item["value"] for item in cookies)
    agent = page.evaluate("navigator.userAgent")
    with CcsutClient({"Cookie": cookie, "User-Agent": agent, "X-Requested-With": "XMLHttpRequest"}) as client:
        grades = client.grades()
    try:
        old = connection_headers()
        unchanged = old["Cookie"] == cookie and old["User-Agent"] == agent
    except Exception:
        unchanged = False
    if not unchanged:
        save_connection(cookie, agent)
    return grades, not unchanged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", action="store_true", help="Open a visible browser for manual authorized login")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=600, help="Health-check interval; not a proven school expiry time")
    parser.add_argument("--login-timeout", type=int, default=600)
    parser.add_argument("--account", default=os.getenv("CCSUT_EXPECTED_ACCOUNT", ""))
    args = parser.parse_args()
    if not args.account:
        parser.error("Set CCSUT_EXPECTED_ACCOUNT or --account to your school account.")
    if len(os.getenv("ADMIN_SESSION_SECRET", "")) < 32:
        parser.error("Use the same ADMIN_SESSION_SECRET as the API, at least 32 characters.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error("Install optional playwright and run python -m playwright install chromium.")
    interval = max(300, args.interval)
    PROFILE.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        PROFILE.chmod(0o700)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE), headless=not args.login)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            while True:
                try:
                    page.goto(ENTRY, wait_until="domcontentloaded", timeout=45000)
                    ready = wait_for_school(page, args.login_timeout if args.login else 45)
                    if not ready:
                        # Do not simulate QR approvals or MFA; keep profile for administrator login.
                        publish("needs_login", message="请管理员使用 --login 在同一服务器浏览器完成学校登录。")
                    else:
                        grades, rotated = export_verified(context, page, args.account)
                        publish("connected", grades=grades, cookie_rotated=rotated)
                except Exception as error:
                    # Exception messages may contain signed URLs; log only the exception class.
                    publish("error", error_type=type(error).__name__)
                if args.once or args.login:
                    break
                page.wait_for_timeout(interval * 1000)
        finally:
            context.close()


if __name__ == "__main__":
    main()

