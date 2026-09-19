"""微信小程序登录：wx.login code -> openid（服务端 jscode2session）。"""
import os

import httpx
from fastapi import HTTPException

WECHAT_SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


def get_openid(code: str) -> str:
    """用 wx.login 的 code 换取 openid；开发环境支持 code=dev 后门。"""
    dev_openid = os.getenv("WECHAT_DEV_OPENID", "").strip()
    if code == "dev" and dev_openid:
        return dev_openid
    appid = os.getenv("WECHAT_APP_ID", "").strip()
    secret = os.getenv("WECHAT_APP_SECRET", "").strip()
    if not appid or not secret:
        raise HTTPException(503, "服务端尚未配置微信 AppID 和 AppSecret")
    try:
        response = httpx.get(WECHAT_SESSION_URL, params={
            "appid": appid, "secret": secret, "js_code": code, "grant_type": "authorization_code",
        }, timeout=8.0)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(502, "微信登录服务暂时不可用") from error
    if not result.get("openid"):
        raise HTTPException(401, result.get("errmsg") or "微信登录失败")
    return result["openid"]
