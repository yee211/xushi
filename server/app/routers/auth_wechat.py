"""微信登录路由（小程序端）：wx.login code 换会话令牌 + 公共配置。"""
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth import get_openid, token_hash
from ..db import connect
from ..rate_limit import login_limiter
from ..redis import redis_set
from ..schemas import WechatLoginIn
from ..settings import settings

router = APIRouter(prefix="/api", tags=["wechat-auth"])


@router.post("/auth/wechat")
def wechat_login(payload: WechatLoginIn, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = login_limiter.hit(client_ip)
    if not allowed:
        return JSONResponse({"detail": "登录尝试过于频繁，请稍后再试"}, status_code=429,
                            headers={"Retry-After": str(retry_after)})
    openid = get_openid(payload.code)
    session_days = settings.session_days
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=session_days)
    with connect() as db:
        user = db.execute("""INSERT INTO users(openid) VALUES(%s)
            ON CONFLICT(openid) DO UPDATE SET last_login_at=CURRENT_TIMESTAMP
            RETURNING id, openid, email, username""", (openid,)).fetchone()
        digest = token_hash(token)
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)",
                   (digest, user["id"], expires))
        db.execute("DELETE FROM sessions WHERE user_id=%s AND expires_at<=CURRENT_TIMESTAMP", (user["id"],))

    ttl_seconds = int(session_days * 86400)
    user_dict = {"id": user["id"], "openid": user["openid"], "email": user["email"], "username": user["username"]}
    redis_set(f"xushi:session:{digest}", json.dumps(user_dict), ex=ttl_seconds)
    return {"token": token, "expires_at": expires.isoformat()}


@router.get("/config")
def public_app_config():
    """小程序前端公共环境配置与审核安全开关。"""
    show_agent = os.getenv("SHOW_AGENT_ENTRY", "true").strip().lower() in ("1", "true", "yes", "on")
    return {"show_agent": show_agent}
