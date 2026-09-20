"""序时统一后端入口：一套服务同时承载网页端 / Android 与微信小程序。

装配顺序：
- lifespan：配置校验 → 日志 → 连接池 → 幂等建表/旧库升级；
- 中间件：CORS（网页跨域）+ 结构化请求日志与 api_request_logs 指标；
- 路由：routers/ 下按领域拆分的模块；
- 静态资源：管理后台 /admin、APK 分发 /downloads、网页单页应用托管。
"""
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# 兼容直接右键运行该脚本 (如 PyCharm / VS Code / 命令行直接运行 python app/main.py)
if __name__ in ("__main__", "__mp_main__") and not __package__:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    __package__ = "app"

import json
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .agent.http_client import close_llm_client
from .db import close_pool, connect, init_db, init_pool, is_pool_ready
from .observability import configure_logging
from .redis import reset_redis_client
from .routers import (
    account_link,
    adjustments,
    admin,
    agent,
    app_update,
    auth_email,
    auth_wechat,
    courses,
    feedback,
    importer,
    schedule_share,
    schedules,
    wecom_callback,
)
from .settings import settings, validate_settings

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
DOWNLOADS_DIR = ROOT / "static" / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_DIR = ROOT / "admin"
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings()
    configure_logging()
    init_pool()
    init_db()
    try:
        yield
    finally:
        close_llm_client()
        close_pool()
        reset_redis_client()


app = FastAPI(title="序时", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(admin.router)
if ADMIN_DIR.exists():
    app.mount("/admin/static", StaticFiles(directory=ADMIN_DIR), name="admin_static")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_index():
    index_file = ADMIN_DIR / "index.html"
    if not index_file.exists():
        from fastapi import HTTPException

        raise HTTPException(404, "管理后台页面未找到")
    return FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico_file = FRONTEND_DIST / "favicon.ico"
    if ico_file.is_file():
        return FileResponse(ico_file, media_type="image/x-icon")
    return Response(status_code=204)


@app.middleware("http")
async def request_metrics(request, call_next):
    """结构化请求日志 + X-Request-ID 透传，记录请求指标至 api_request_logs。"""
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        duration = round((time.perf_counter() - started) * 1000)
        logger.info(json.dumps({"event": "http_request", "request_id": request_id,
            "method": request.method, "path": request.url.path, "status": status_code,
            "duration_ms": duration}))
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        duration = round((time.perf_counter() - started) * 1000)
        logger.exception(json.dumps({"event": "http_request", "request_id": request_id,
            "method": request.method, "path": request.url.path, "status": 500, "duration_ms": duration}))
        raise
    finally:
        path = request.url.path
        if is_pool_ready() and not path.startswith("/admin/static") and not path.endswith((".ico", ".png", ".jpg", ".css", ".js")):
            try:
                duration = round((time.perf_counter() - started) * 1000)
                with connect() as db:
                    db.execute("""INSERT INTO api_request_logs(method, path, status, duration_ms)
                        VALUES(%s, %s, %s, %s)""", (request.method, path[:250], status_code, duration))
            except Exception:
                pass


# 注册业务路由模块
app.include_router(auth_email.router)
app.include_router(auth_wechat.router)
app.include_router(account_link.router)
app.include_router(schedules.router)
app.include_router(schedule_share.router)
app.include_router(courses.router)
app.include_router(adjustments.router)
app.include_router(importer.router)
app.include_router(agent.router)
app.include_router(wecom_callback.router)
app.include_router(app_update.router)
app.include_router(feedback.router)

# 挂载静态下载目录（供 Android APK 直接下载更新）
app.mount("/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")


@app.get("/api/health")
def health():
    """就绪探针：同时检查数据库连接。"""
    with connect() as db:
        db.execute("SELECT 1")
    return {"ok": True}


@app.get("/api/live")
def live():
    """存活探针：仅确认应用进程能够响应。"""
    return {"ok": True}


# 托管网页端单页应用静态资源（构建产物位于 frontend/dist）
if FRONTEND_DIST.exists():
    if (FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        candidate = FRONTEND_DIST / path
        return FileResponse(candidate if candidate.is_file() else FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
