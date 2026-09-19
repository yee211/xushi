"""Android 客户端版本检测与 APK 下载直线路由。"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/app", tags=["App Update"])
logger = logging.getLogger("classschedule")

# server/ 目录（容器内为 /app，data 由 compose 挂载至此）；本地开发回退仓库根 data/
SERVER_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = SERVER_ROOT / "data" / "app_version.json"
if not VERSION_FILE.is_file():
    VERSION_FILE = SERVER_ROOT.parent / "data" / "app_version.json"

DEFAULT_VERSION_INFO = {
    "versionCode": 1,
    "versionName": "2.0.0",
    "minVersionCode": 1,
    "title": "发现新版本",
    "changelog": [
        "性能与稳定性优化"
    ],
    "downloadUrl": "https://api.tanzeng.xyz/downloads/ClassSchedule.apk",
    "forceUpdate": False
}


class AppVersionResponse(BaseModel):
    versionCode: int
    versionName: str
    minVersionCode: int = 1
    title: str = "发现新版本"
    changelog: list[str] = Field(default_factory=list)
    downloadUrl: str
    backupDownloadUrl: str | None = None
    forceUpdate: bool = False


@router.get("/version", response_model=AppVersionResponse)
def get_app_version() -> AppVersionResponse:
    """获取移动端最新版本信息与下载链接"""
    if VERSION_FILE.is_file():
        try:
            with open(VERSION_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return AppVersionResponse(**data)
        except (OSError, ValueError, TypeError) as error:
            logger.error("读取版本元数据失败: %s", error.__class__.__name__)
    return AppVersionResponse(**DEFAULT_VERSION_INFO)
