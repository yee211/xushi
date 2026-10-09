"""Shared read-only school timetable queries; school credentials stay admin-only."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..services import academic, academic_binding, academic_jobs, academic_login, schedule_backups
from .admin import require_superadmin

router = APIRouter(tags=["academic"])


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except academic.AcademicError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message}) from error


class ConnectionIn(BaseModel):
    cookie: str = Field(min_length=1, max_length=16000)
    user_agent: str = Field(default="Mozilla/5.0", max_length=500)


@router.get("/api/academic/students")
def students(grade: str | None = Query(default=None, pattern=r"^20\d{2}$"), name: str = Query(default="", max_length=80),
             class_name: str = Query(default="", max_length=80),
             major: str = Query(default="", max_length=80), q: str = Query(default="", max_length=80), user=Depends(get_current_user)):
    if q.strip():
        return invoke(academic.search_keyword, q.strip())
    if not grade:
        raise HTTPException(422, "请输入搜索关键词")
    name, class_name = name.strip(), class_name.strip()
    if not name and not class_name and not major.strip():
        raise HTTPException(422, "请输入专业、班级或姓名")
    return invoke(academic.search_students, grade, name, class_name, major.strip())


@router.get("/api/academic/students/{student_id}/terms")
def terms(student_id: str, user=Depends(get_current_user)):
    return invoke(academic.available_terms, student_id)


@router.get("/api/admin/academic/connection")
def connection(admin=Depends(require_superadmin)):
    try:
        with academic.CcsutClient() as client:
            values = client.grades()
        return {"connected": True, "grades": values, "browser": academic.browser_status()}
    except academic.AcademicError as error:
        return {"connected": False, "code": error.code, "message": error.message, "browser": academic.browser_status()}


@router.put("/api/admin/academic/connection")
def set_connection(payload: ConnectionIn, admin=Depends(require_superadmin)):
    if "\r" in payload.cookie or "\n" in payload.cookie or "\r" in payload.user_agent or "\n" in payload.user_agent:
        raise HTTPException(422, "会话配置不可包含换行")
    headers = {"Cookie": payload.cookie, "User-Agent": payload.user_agent, "X-Requested-With": "XMLHttpRequest"}
    with invoke(academic.CcsutClient, headers) as client:
        values = invoke(client.grades)
    invoke(academic.save_connection, payload.cookie, payload.user_agent)
    return {"connected": True, "grades": values}


class BindingIn(BaseModel):
    student_id: str = Field(min_length=8, max_length=200)


@router.get("/api/academic/binding")
def binding(user=Depends(get_current_user)):
    return invoke(academic_binding.read_binding, user["id"], use_cache=True)


@router.put("/api/academic/binding")
def set_binding(payload: BindingIn, user=Depends(get_current_user)):
    return invoke(academic_binding.bind, user["id"], payload.student_id)


@router.delete("/api/academic/binding")
def remove_binding(user=Depends(get_current_user)):
    return academic_binding.unbind(user["id"])


class SyncIn(BaseModel):
    term: str = Field(pattern=r"^\d{4}-\d{4}-[12]$")
    refresh: bool = False


@router.get("/api/academic/backups")
def backups(user=Depends(get_current_user)):
    return schedule_backups.list_backups(user["id"])


@router.post("/api/academic/backups/{backup_id}/restore")
def restore_backup(backup_id: int, user=Depends(get_current_user)):
    return schedule_backups.restore(user["id"], backup_id)


class SchoolCredentialsIn(BaseModel):
    account: str = Field(pattern=r"^1[0-9]{10}$")


class SchoolLoginCommandIn(BaseModel):
    job_id: str = Field(min_length=1, max_length=80)
    action: str = Field(pattern=r"^(send_code|submit_code|stop)$")
    code: str = Field(default="", max_length=32)


@router.get("/api/admin/academic/login/status")
def school_login_status(admin=Depends(require_superadmin)):
    return academic_login.status()


@router.put("/api/admin/academic/login/credentials")
def school_credentials(payload: SchoolCredentialsIn, admin=Depends(require_superadmin)):
    if academic_login.status()["running"]:
        raise HTTPException(409, "请先停止登录维护，再更换手机号")
    invoke(academic_login.save_credentials, payload.account)
    return academic_login.status()


@router.delete("/api/admin/academic/login/credentials")
def delete_school_credentials(admin=Depends(require_superadmin)):
    invoke(academic_login.delete_credentials)
    return academic_login.status()


class StartLoginIn(BaseModel):
    visible: bool = False


@router.post("/api/admin/academic/login/start")
def start_school_login(payload: StartLoginIn | None = None, visible: bool = Query(default=False), admin=Depends(require_superadmin)):
    is_visible = (payload.visible if payload else False) or visible
    return invoke(academic_login.start, visible=is_visible)


@router.post("/api/admin/academic/login/command")
def school_login_command(payload: SchoolLoginCommandIn, admin=Depends(require_superadmin)):
    return invoke(academic_login.command, payload.action, payload.job_id, payload.code)


@router.get("/api/admin/academic/login/diagnostic")
def school_login_diagnostic(admin=Depends(require_superadmin)):
    from fastapi.responses import FileResponse

    path = academic_login.DIRECTORY / "login-page.png"
    if not path.exists():
        raise HTTPException(404, "暂时没有登录页面诊断")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/api/academic/binding/sync/tasks", status_code=202)
def create_sync_task(payload: SyncIn, user=Depends(get_current_user)):
    return academic_jobs.enqueue(user["id"], payload.term, payload.refresh)


@router.get("/api/academic/binding/sync/tasks/latest")
def latest_sync_task(user=Depends(get_current_user)):
    return {"task": academic_jobs.read(user["id"])}


@router.get("/api/academic/binding/sync/tasks/{job_id}")
def get_sync_task(job_id: UUID, user=Depends(get_current_user)):
    return academic_jobs.read(user["id"], job_id)


@router.get("/api/admin/academic/sync/status")
def sync_status(admin=Depends(require_superadmin)):
    from ..db import connect
    with connect() as db:
        bound_count = db.execute("SELECT COUNT(*) AS count FROM academic_bindings").fetchone()["count"]
        recent = db.execute("SELECT id,user_id,term,state,source,attempts,error,created_at,updated_at FROM academic_sync_jobs ORDER BY created_at DESC LIMIT 30").fetchall()
        counts = db.execute("SELECT state,COUNT(*) AS count FROM academic_sync_jobs GROUP BY state").fetchall()
        pause = db.execute("SELECT pause_until FROM academic_sync_control WHERE id=1").fetchone()
        day = db.execute("SELECT run_date,created_at FROM academic_sync_days ORDER BY run_date DESC LIMIT 1").fetchone()
    return {"bound_count": bound_count, "recent": recent, "counts": {row['state']: row['count'] for row in counts}, "last_daily_run": day, "timezone": "Asia/Shanghai", "pause_until": pause["pause_until"] if pause else None}


@router.post("/api/admin/academic/sync/start", status_code=202)
def start_all_sync(admin=Depends(require_superadmin)):
    return academic_jobs.enqueue_all()


@router.get("/api/admin/academic/directory/status")
def directory_status(admin=Depends(require_superadmin)):
    from ..services import academic_directory
    return academic_directory.status()


@router.post("/api/admin/academic/directory/refresh", status_code=202)
def refresh_directory(admin=Depends(require_superadmin)):
    from ..services import academic_directory
    return academic_directory.enqueue()
