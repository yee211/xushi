"""Agent 渠道绑定路由（小程序端）：绑定状态、绑定码、ClawBot 扫码连接、调试入口。"""
import logging
import os
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import httpx
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..agent.orchestrator import handle_message
from ..agent.tools import AgentContext, ScheduleTools
from ..auth import get_current_user
from ..channels.weixin.client import DEFAULT_API_BASE, ILinkClient, trusted_tencent_url
from ..channels.weixin.login_session import (
    create_session,
    delete_session,
    load_session,
    load_session_by_id,
    reserve_start,
    update_session,
)
from ..channels.weixin.protocol import Credentials
from ..channels.weixin.store import credential_key, save_account
from ..db import connect
from ..schemas import AgentMessageIn, BindingCodeIn, WeixinLoginPollIn
from ..services.binding import create_binding_code

router = APIRouter(prefix="/api", tags=["agent-bindings"])
logger = logging.getLogger("uvicorn.error")

ACTIVE_PROVIDER = os.getenv("AGENT_CHANNEL_PROVIDER", "weixin_ilink").strip() or "weixin_ilink"
# 可同时在多个渠道绑定助手（各渠道身份独立、互不影响）
BINDING_PROVIDERS = ("weixin_ilink", "wecom")


@router.get("/agent-bindings")
def agent_binding_status(user=Depends(get_current_user)):
    with connect() as db:
        rows = db.execute("""SELECT provider,created_at,last_seen_at FROM user_identities
            WHERE user_id=%s AND provider=ANY(%s)""", (user["id"], list(BINDING_PROVIDERS))).fetchall()
    by_provider = {row["provider"]: row for row in rows}
    channels = [{"provider": provider, "bound": provider in by_provider,
                 "created_at": by_provider[provider]["created_at"].isoformat() if provider in by_provider else None,
                 "last_seen_at": by_provider[provider]["last_seen_at"].isoformat() if provider in by_provider else None}
                for provider in BINDING_PROVIDERS]
    active = next((item for item in channels if item["bound"]), channels[0])
    return {"channels": channels, "bound": active["bound"], "provider": active["provider"],
            "created_at": active["created_at"], "last_seen_at": active["last_seen_at"]}


@router.post("/agent-bindings/code")
def new_agent_binding_code(payload: BindingCodeIn | None = None, user=Depends(get_current_user)):
    provider = (payload.provider.strip() if payload and payload.provider.strip() else "") or ACTIVE_PROVIDER
    if provider not in BINDING_PROVIDERS:
        raise HTTPException(404, "不支持的绑定渠道")
    ttl = int(os.getenv("BINDING_CODE_TTL_SECONDS", "300"))
    with connect() as db:
        code, expires = create_binding_code(db, user["id"], provider, ttl)
    return {"code": code, "expires_at": expires.isoformat(), "provider": provider}


@router.delete("/agent-bindings/{provider}", status_code=204)
def delete_agent_binding(provider: str, user=Depends(get_current_user)):
    if provider not in BINDING_PROVIDERS:
        raise HTTPException(404, "接口不存在")
    with connect() as db:
        db.execute("DELETE FROM user_identities WHERE user_id=%s AND provider=%s", (user["id"], provider))
        if provider == "weixin_ilink":
            db.execute("""UPDATE channel_accounts SET status='inactive',updated_at=CURRENT_TIMESTAMP
                WHERE provider='weixin_ilink' AND owner_user_id=%s""", (user["id"],))


@router.post("/integrations/weixin/login")
def start_weixin_login(user=Depends(get_current_user)):
    """Generate a ClawBot QR code without exposing iLink credentials to the mini program."""
    try:
        credential_key()
        reserve_start(user["id"])
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    client = ILinkClient()
    try:
        result = client.get_login_qrcode()
    except (httpx.HTTPError, RuntimeError) as error:
        logger.warning("weixin QR start failed: %s", error)
        raise HTTPException(502, "暂时无法生成微信 ClawBot 二维码") from error
    finally:
        client.close()
    qr_token = str(result.get("qrcode") or "")
    image_url = str(result.get("qrcode_img_content") or "")
    if not qr_token or not image_url:
        raise HTTPException(502, "腾讯 iLink 未返回有效二维码")
    try:
        session = create_session(user["id"], qr_token, image_url)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    return {"session_id": session["id"],
            "qrcode_path": f"/api/integrations/weixin/login/{session['id']}/qrcode", "expires_in": 600}


@router.get("/integrations/weixin/login/{session_id}/qrcode")
def weixin_login_qrcode(session_id: str):
    """Render an unguessable, short-lived login session as a same-origin PNG."""
    try:
        session = load_session_by_id(session_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    image = qrcode.make(session["image_url"])
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/integrations/weixin/login/{session_id}/poll")
def poll_weixin_login(session_id: str, body: WeixinLoginPollIn, user=Depends(get_current_user)):
    try:
        session = load_session(session_id, user["id"])
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    client = ILinkClient()
    try:
        result = client.poll_qrcode(session["qrcode"], body.verify_code, session.get("redirect_host", ""))
    except (httpx.HTTPError, RuntimeError) as error:
        logger.warning("weixin QR poll failed: %s", error)
        raise HTTPException(502, "暂时无法查询扫码状态") from error
    finally:
        client.close()
    state = str(result.get("status") or "wait")
    if state == "scaned_but_redirect":
        session["redirect_host"] = str(result.get("redirect_host") or "")
        update_session(session)
    if state == "confirmed":
        account_id = str(result.get("ilink_bot_id") or "")
        bot_token = str(result.get("bot_token") or "")
        sender_id = str(result.get("ilink_user_id") or "")
        try:
            base_url = trusted_tencent_url(str(result.get("baseurl") or DEFAULT_API_BASE))
        except RuntimeError as error:
            raise HTTPException(502, str(error)) from error
        if not account_id or not bot_token or not sender_id:
            raise HTTPException(502, "扫码成功，但腾讯 iLink 返回的账号信息不完整")
        credentials = Credentials(account_id, bot_token, base_url, sender_id)
        with connect() as db:
            db.execute("""UPDATE channel_accounts SET status='inactive',updated_at=CURRENT_TIMESTAMP
                WHERE provider='weixin_ilink' AND owner_user_id=%s AND account_id<>%s""",
                       (user["id"], account_id))
            save_account(db, credentials, user["id"])
            db.execute("DELETE FROM user_identities WHERE user_id=%s AND provider='weixin_ilink'",
                       (user["id"],))
            db.execute("""INSERT INTO user_identities(user_id,provider,provider_user_id)
                VALUES(%s,'weixin_ilink',%s) ON CONFLICT(provider,provider_user_id) DO UPDATE SET
                user_id=EXCLUDED.user_id,last_seen_at=CURRENT_TIMESTAMP""", (user["id"], sender_id))
            db.execute("""UPDATE user_identities SET account_id=%s
                WHERE user_id=%s AND provider='weixin_ilink'""", (account_id, user["id"]))
        delete_session(session_id)
        return {"status": "confirmed", "connected": True}
    if state in {"expired", "verify_code_blocked", "binded_redirect"}:
        delete_session(session_id)
    return {"status": state, "connected": False}


@router.post("/agent/debug/message")
def agent_debug_message(payload: AgentMessageIn, user=Depends(get_current_user)):
    """Development-only entry point for validating Agent queries before channel integration."""
    if os.getenv("APP_ENV", "production").strip().lower() not in {"development", "dev"}:
        raise HTTPException(404, "接口不存在")
    timezone = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))
    context = AgentContext(user_id=user["id"], now=datetime.now(timezone), timezone=str(timezone))
    with connect() as db:
        return handle_message(payload.message, ScheduleTools(db, context))
