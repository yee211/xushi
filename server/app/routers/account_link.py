"""账号互通路由：App/网页账号与微信小程序账号绑定（合并为同一账号）。

- POST /api/account/link/code  生成六位绑定码（App/网页，JWT）；
- POST /api/account/link       小程序输入绑定码完成绑定（会话令牌）；
- DELETE /api/account/link     解除微信绑定（双端均可）；
- GET  /api/account/link       查询当前账号绑定状态。
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from ..auth import get_current_user
from ..db import connect
from ..rate_limit import link_limiter
from ..schemas import AccountLinkIn
from ..services import account_link as service
from ..services.account_link import AccountLinkError

router = APIRouter(prefix="/api/account/link", tags=["account-link"])


def _status(error: AccountLinkError) -> int:
    return 409 if error.code in ("ALREADY_BOUND", "TARGET_BOUND", "WX_HAS_EMAIL") else 400


@router.get("")
def link_status(user=Depends(get_current_user)):
    with connect() as db:
        row = db.execute("SELECT openid, email, username FROM users WHERE id=%s",
                         (user["id"],)).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在")
    return {"openid_bound": bool(row["openid"]), "email": row["email"] or "",
            "username": row["username"] or ""}


@router.post("/code")
def new_link_code(user=Depends(get_current_user)):
    ttl = int(os.getenv("BINDING_CODE_TTL_SECONDS", "300"))
    with connect() as db:
        try:
            code, expires = service.create_link_code(db, user["id"], ttl)
        except AccountLinkError as error:
            raise HTTPException(_status(error), error.message) from error
    return {"code": code, "expires_at": expires.isoformat(), "provider": service.PROVIDER}


@router.post("")
def link_account(payload: AccountLinkIn, user=Depends(get_current_user)):
    """小程序提交绑定码。按用户限流，防止在五分钟有效期内遍历六位码。"""
    allowed, retry_after = link_limiter.hit(str(user["id"]))
    if not allowed:
        return JSONResponse({"detail": "尝试过于频繁，请稍后再试"},
                            status_code=429, headers={"Retry-After": str(retry_after)})
    with connect() as db:
        try:
            summary = service.link_wechat_account(db, payload.code, user)
        except AccountLinkError as error:
            raise HTTPException(_status(error), error.message) from error
    return {"linked": True, **summary}


@router.delete("", status_code=204)
def unlink_account(user=Depends(get_current_user)):
    with connect() as db:
        try:
            service.unlink_wechat(db, user["id"])
        except AccountLinkError as error:
            raise HTTPException(_status(error), error.message) from error
    return Response(status_code=204)
