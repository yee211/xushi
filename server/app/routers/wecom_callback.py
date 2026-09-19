"""企业微信智能机器人回调路由（URL 验证 + 加密消息接收）。"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from ..channels.wecom import WeComCryptoError, handle_callback, verify_callback_url, wecom_settings

router = APIRouter(prefix="/api/integrations/wecom", tags=["wecom"])


@router.get("/callback")
def wecom_callback_verify(request: Request):
    """企业微信后台「验证 URL 有效性」：验签并原样返回解密后的 echostr。"""
    settings = wecom_settings()
    if not settings:
        raise HTTPException(404, "接口不存在")
    params = request.query_params
    try:
        echo = verify_callback_url(settings, params.get("msg_signature", ""), params.get("timestamp", ""),
                                   params.get("nonce", ""), params.get("echostr", ""))
    except WeComCryptoError as error:
        raise HTTPException(403, str(error)) from error
    return PlainTextResponse(echo)


@router.post("/callback")
async def wecom_callback(request: Request, background_tasks: BackgroundTasks):
    """接收加密消息：验签解密后立即回空包，答复经应用消息异步推送。"""
    settings = wecom_settings()
    if not settings:
        raise HTTPException(404, "接口不存在")
    params = request.query_params
    try:
        handle_callback(settings, await request.body(), params.get("msg_signature", ""),
                        params.get("timestamp", ""), params.get("nonce", ""), background_tasks)
    except WeComCryptoError as error:
        raise HTTPException(400, str(error)) from error
    return Response("")
