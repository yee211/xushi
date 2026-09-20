"""课表分享与口令导入路由：生成 6 位分享提取码、解析预览与一键克隆导入。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..db import connect
from ..services import schedule_share as service
from ..services.schedule_share import ShareError

router = APIRouter(prefix="/api/schedules", tags=["schedule-share"])


class ShareImportIn(BaseModel):
    custom_name: str | None = Field(default=None, max_length=80)


def _handle_share_error(error: ShareError) -> HTTPException:
    status_map = {
        "NOT_FOUND": 404,
        "EXPIRED": 410,
        "DELETED": 410,
        "INVALID_FORMAT": 400,
        "SELF_IMPORT": 409,
    }
    status = status_map.get(error.code, 400)
    return HTTPException(status, error.message)


@router.post("/{schedule_id}/share")
def create_schedule_share(schedule_id: int, user=Depends(get_current_user)):
    """为当前指定课表生成或获取仍在有效期的 6 位提取分享码。"""
    with connect() as db:
        try:
            result = service.create_or_get_share_code(db, user["id"], schedule_id)
        except ShareError as error:
            raise _handle_share_error(error) from error
    return {
        **result,
        "expires_at": result["expires_at"].isoformat() if hasattr(result["expires_at"], "isoformat") else str(result["expires_at"]),
    }


@router.get("/share/{code}")
def preview_shared_schedule(code: str, user=Depends(get_current_user)):
    """通过 6 位口令解析并预览课表基本信息（名称、学期、课程总数等）。"""
    with connect() as db:
        try:
            info = service.get_share_info(db, code)
        except ShareError as error:
            raise _handle_share_error(error) from error
    return {
        **info,
        "start_date": str(info["start_date"]) if info["start_date"] else None,
        "end_date": str(info["end_date"]) if info["end_date"] else None,
        "expires_at": info["expires_at"].isoformat() if hasattr(info["expires_at"], "isoformat") else str(info["expires_at"]),
    }


@router.post("/share/{code}/import")
def import_schedule_by_code(code: str, payload: ShareImportIn = None, user=Depends(get_current_user)):
    """输入分享码一键克隆导入课表及其全部课程。"""
    custom_name = payload.custom_name if payload else None
    with connect() as db:
        try:
            result = service.import_shared_schedule(db, user["id"], code, custom_name)
        except ShareError as error:
            raise _handle_share_error(error) from error
    return result
