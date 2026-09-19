"""Interactive QR login for a Weixin ClawBot account."""
import time

from ...db import connect, init_db, init_pool
from .client import DEFAULT_API_BASE, ILinkClient
from .protocol import Credentials
from .store import save_account


def login() -> Credentials:
    client = ILinkClient()
    try:
        result = client.get_login_qrcode()
        qrcode = str(result.get("qrcode") or "")
        display = str(result.get("qrcode_img_content") or qrcode)
        if not qrcode:
            raise RuntimeError("腾讯 iLink 未返回登录二维码")
        print("请使用微信扫描并确认以下 ClawBot 授权二维码：", flush=True)
        print(display, flush=True)
        redirect_host = ""
        verify_code = ""
        while True:
            status = client.poll_qrcode(qrcode, verify_code=verify_code, redirect_host=redirect_host)
            verify_code = ""
            state = str(status.get("status") or "wait")
            if state == "confirmed":
                credentials = Credentials(
                    account_id=str(status.get("ilink_bot_id") or ""),
                    bot_token=str(status.get("bot_token") or ""),
                    base_url=str(status.get("baseurl") or DEFAULT_API_BASE),
                    admin_user_id=str(status.get("ilink_user_id") or ""),
                )
                if not credentials.account_id or not credentials.bot_token:
                    raise RuntimeError("扫码已确认，但腾讯 iLink 未返回完整凭证")
                init_pool()
                init_db()
                with connect() as db:
                    save_account(db, credentials)
                print(f"微信 ClawBot 已连接：{credentials.account_id}", flush=True)
                return credentials
            if state == "expired":
                raise RuntimeError("二维码已过期，请重新运行登录命令")
            if state == "need_verifycode":
                verify_code = input("请输入微信中显示的验证码：").strip()
            if state == "verify_code_blocked":
                raise RuntimeError("验证码尝试次数过多，请重新运行登录命令")
            if state == "binded_redirect":
                raise RuntimeError("该 ClawBot 已绑定；请先解除原连接后重新扫码")
            if state == "scaned_but_redirect":
                redirect_host = str(status.get("redirect_host") or redirect_host)
            time.sleep(1)
    finally:
        client.close()
