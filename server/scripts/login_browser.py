"""一键启动可视 Chrome 浏览器进行学校教务系统登录。

运行方式：
    venv\\Scripts\\python scripts/login_browser.py
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.academic import CcsutClient, save_connection
from app.services.academic_login import PROFILE, continue_school_login

ENTRY = "https://tls.ccsut.cn/admin/jwxtgld/kbcx/xskblist"


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误: 请先安装 playwright 依赖: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    print("=" * 60)
    print("🚀 正在启动学校教务可视登录浏览器...")
    print("💡 提示: 您可以在弹出的浏览器窗口中直接输入账号密码验证码、点击「统一认证登录」，或使用微信扫码。")
    print("💡 登录成功并进入教务系统后，脚本会自动抓取会话 Cookie 并保存！")
    print("=" * 60)

    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            args=["--start-maximized"],
        )
        context.set_default_timeout(20000)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(ENTRY, wait_until="domcontentloaded", timeout=45000)
            continued = False
            deadline = time.monotonic() + 600

            while time.monotonic() < deadline:
                if page.is_closed():
                    print("\n⚠️ 浏览器窗口已被手动关闭。")
                    break

                page.wait_for_timeout(500)
                loc = urlsplit(page.url)

                if loc.hostname == "tls.ccsut.cn":
                    # 如果在登录页，自动辅助点击统一认证登录
                    if not continued and continue_school_login(page):
                        continued = True
                        print("👉 检测到教务登录页，已自动点击「统一认证」->「统一认证登录」")

                    # 检查是否已成功进入教务课表主页
                    if page.locator("#xm").count() and page.locator(".list_sslct").count():
                        print("✅ 已成功进入教务系统页面！正在提取已授权会话...")
                        cookies = context.cookies([ENTRY])
                        cookie_str = "; ".join(item["name"] + "=" + item["value"] for item in cookies)
                        agent = page.evaluate("navigator.userAgent")

                        with CcsutClient({"Cookie": cookie_str, "User-Agent": agent, "X-Requested-With": "XMLHttpRequest"}) as client:
                            grades = client.grades()

                        save_connection(cookie_str, agent)
                        print(f"🎉 登录成功！教务连接已保存（可用年级: {grades}）")
                        print("👉 后台已同步可用，您现在可以关闭浏览器窗口或继续使用。")
                        page.wait_for_timeout(3000)
                        break
                    elif continued and loc.path != urlsplit(ENTRY).path:
                        try:
                            page.goto(ENTRY, wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass
            else:
                print("⏱️ 登录等待已超时（10 分钟）。")
        finally:
            context.close()


if __name__ == "__main__":
    main()
