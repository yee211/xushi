"""HTTP client for Tencent's documented Weixin iLink Bot protocol."""
import base64
import os
import secrets
import uuid
from urllib.parse import urljoin, urlparse

import httpx

from .protocol import Credentials

DEFAULT_API_BASE = "https://ilinkai.weixin.qq.com"


class ILinkError(RuntimeError):
    pass


def trusted_tencent_url(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (hostname == "qq.com" or hostname.endswith(".qq.com")):
        raise ILinkError("微信 iLink API 地址不是受信任的腾讯 HTTPS 域名")
    return value


def _client_version(version: str) -> str:
    try:
        major, minor, patch = (int(part) for part in version.split(".")[:3])
    except (TypeError, ValueError):
        major, minor, patch = 0, 0, 0
    return str(((major & 0xff) << 16) | ((minor & 0xff) << 8) | (patch & 0xff))


class ILinkClient:
    def __init__(self, credentials: Credentials | None = None, *, http: httpx.Client | None = None):
        self.credentials = credentials
        self.version = os.getenv("WEIXIN_ILINK_CHANNEL_VERSION", "2.4.8").strip() or "2.4.8"
        self.app_id = os.getenv("WEIXIN_ILINK_APP_ID", "bot").strip() or "bot"
        self.bot_agent = os.getenv("WEIXIN_ILINK_BOT_AGENT", "XuShiSchedule/1.0.0").strip()
        self.route_tag = os.getenv("WEIXIN_ILINK_ROUTE_TAG", "").strip()
        self.http = http or httpx.Client(follow_redirects=False)

    def close(self) -> None:
        self.http.close()

    def _common_headers(self) -> dict[str, str]:
        headers = {"iLink-App-Id": self.app_id,
                   "iLink-App-ClientVersion": _client_version(self.version)}
        if self.route_tag:
            headers["SKRouteTag"] = self.route_tag
        return headers

    def _json_headers(self, token: str = "") -> dict[str, str]:
        uin = str(secrets.randbits(32)).encode()
        headers = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                   "X-WECHAT-UIN": base64.b64encode(uin).decode(), **self._common_headers()}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": self.version, "bot_agent": self.bot_agent}

    def _post(self, path: str, body: dict, *, timeout: float = 15.0, authenticated: bool = True) -> dict:
        token = self.credentials.bot_token if authenticated and self.credentials else ""
        base = self.credentials.base_url if authenticated and self.credentials else DEFAULT_API_BASE
        base = trusted_tencent_url(base)
        payload = dict(body)
        if authenticated:
            if not token:
                raise ILinkError("缺少微信 iLink bot_token")
            payload["base_info"] = self._base_info()
        response = self.http.post(urljoin(base.rstrip("/") + "/", path.lstrip("/")), json=payload,
                                  headers=self._json_headers(token), timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ILinkError("微信 iLink 返回了非 JSON 对象")
        return data

    def get_login_qrcode(self, recent_tokens: list[str] | None = None) -> dict:
        return self._post("/ilink/bot/get_bot_qrcode?bot_type=3",
                          {"local_token_list": (recent_tokens or [])[:10]}, authenticated=False)

    def poll_qrcode(self, qrcode: str, verify_code: str = "", redirect_host: str = "") -> dict:
        params = {"qrcode": qrcode}
        if verify_code:
            params["verify_code"] = verify_code
        base = redirect_host or DEFAULT_API_BASE
        if "://" not in base:
            base = f"https://{base}"
        base = trusted_tencent_url(base)
        try:
            response = self.http.get(urljoin(base.rstrip("/") + "/", "/ilink/bot/get_qrcode_status"),
                                     params=params, headers=self._common_headers(), timeout=40.0)
        except httpx.RequestError:
            return {"status": "wait"}
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ILinkError("微信扫码状态返回格式错误")
        return data

    def get_updates(self, cursor: str = "", *, timeout: float | None = None) -> dict:
        poll_timeout = timeout if timeout is not None else float(os.getenv("WEIXIN_ILINK_POLL_TIMEOUT_SECONDS", "2.0"))
        try:
            data = self._post("/ilink/bot/getupdates", {"get_updates_buf": cursor}, timeout=poll_timeout)
        except (httpx.ReadTimeout, httpx.TimeoutException):
            # Normal long-poll expiration when no new messages arrived during the window.
            return {"msgs": [], "get_updates_buf": cursor, "ret": 0}
        ret = data.get("ret", data.get("errcode", 0))
        if ret:
            raise ILinkError(f"微信收取消息失败：{ret} {data.get('errmsg', '')}".strip())
        return data

    def send_text(self, to_user_id: str, text: str, context_token: str = "", *, client_id: str,
                  run_id: str = "") -> None:
        max_chars = max(100, min(int(os.getenv("WEIXIN_ILINK_MAX_REPLY_CHARS", "4000")), 10000))
        msg: dict = {"from_user_id": "", "to_user_id": to_user_id, "client_id": client_id,
                     "message_type": 2, "message_state": 2,
                     "item_list": [{"type": 1, "text_item": {"text": text[:max_chars]}}]}
        if context_token:
            msg["context_token"] = context_token
        if run_id:
            msg["run_id"] = run_id
        data = self._post("/ilink/bot/sendmessage", {"msg": msg})
        if data.get("ret", 0):
            raise ILinkError(f"微信发送消息失败：{data.get('ret')} {data.get('errmsg', '')}".strip())

    def notify(self, started: bool) -> None:
        path = "/ilink/bot/msg/notifystart" if started else "/ilink/bot/msg/notifystop"
        data = self._post(path, {})
        if data.get("ret", 0):
            raise ILinkError(f"微信生命周期通知失败：{data.get('ret')} {data.get('errmsg', '')}".strip())

    def get_config(self, ilink_user_id: str, context_token: str = "") -> dict:
        """Fetch bot config for user including typing_ticket."""
        payload: dict = {"ilink_user_id": ilink_user_id}
        if context_token:
            payload["context_token"] = context_token
        return self._post("/ilink/bot/getconfig", payload, timeout=10.0)

    def send_typing(self, to_user_id: str, typing_ticket: str, status: int = 1) -> None:
        """Send typing status indicator (1=typing, 2=cancel)."""
        payload = {"ilink_user_id": to_user_id, "typing_ticket": typing_ticket, "status": status}
        data = self._post("/ilink/bot/sendtyping", payload, timeout=10.0)
        if data.get("ret", 0):
            raise ILinkError(f"微信发送输入状态失败：{data.get('ret')} {data.get('errmsg', '')}".strip())

    def send_typing_indicator(self, to_user_id: str, context_token: str = "", status: int = 1) -> None:
        """Best-effort send typing indicator; caches typing_ticket and swallows errors safely."""
        if not hasattr(self, "_typing_tickets"):
            self._typing_tickets: dict[str, str] = {}
        try:
            ticket = self._typing_tickets.get(to_user_id)
            if not ticket:
                cfg = self.get_config(to_user_id, context_token)
                ticket = str(cfg.get("typing_ticket") or "")
                if ticket:
                    self._typing_tickets[to_user_id] = ticket
            if ticket:
                self.send_typing(to_user_id, ticket, status)
        except Exception:
            pass


def reply_client_id(account_id: str, message_id: str) -> str:
    """Stable ID lets the backend suppress a repeated send after a worker crash."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wx-schedule:{account_id}:{message_id}"))
