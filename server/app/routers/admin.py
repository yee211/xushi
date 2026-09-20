"""管理后台路由：数据大盘、流量、反馈处理、LLM 动态配置与管理员管理。

静态页面在 server/admin/，由 main.py 挂载到 /admin。
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import connect, row_dict
from ..rate_limit import SlidingWindowLimiter
from ..services.feedback import CATEGORY_LABELS, feedback_number
from ..services.llm_config import SCOPES, public_config, reset_llm_config, save_llm_config, test_llm_connection

router = APIRouter(prefix="/api/admin", tags=["admin"])
FEEDBACK_STATUSES = {"pending", "processing", "resolved", "closed"}
admin_login_limiter = SlidingWindowLimiter(limit=8, window_seconds=300)


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AdminCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="admin", pattern=r"^(admin|superadmin)$")


class FeedbackUpdateIn(BaseModel):
    status: str = Field(pattern=r"^(pending|processing|resolved|closed)$")
    admin_note: str = Field(default="", max_length=1000)


class LlmConfigIn(BaseModel):
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    timeout_seconds: float = Field(ge=2, le=120)
    max_tokens: int = Field(ge=100, le=16000)
    enable_thinking: bool = False


class LlmTestIn(BaseModel):
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    timeout_seconds: float = Field(default=10.0, ge=1, le=30)
    enable_thinking: bool = False


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2:sha256:100000${salt}${dk.hex()}"


def verify_password(password: str, hash_str: str) -> bool:
    try:
        algo, salt, dk_hex = hash_str.split("$")
        if not algo.startswith("pbkdf2:sha256"):
            return False
        iterations = int(algo.split(":")[2])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _settings() -> tuple[str, str, str]:
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
    if not username or not password or len(secret) < 32:
        raise HTTPException(503, "管理后台尚未配置")
    return username, password, secret


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(username: str) -> str:
    _, _, secret = _settings()
    seconds = max(900, min(86400, int(os.getenv("ADMIN_SESSION_SECONDS", "28800"))))
    payload = f"{username}:{int(time.time()) + seconds}:{secrets.token_hex(12)}"
    return f"{payload}:{_sign(payload, secret)}"


def current_admin(authorization: str | None = Header(default=None)) -> str:
    username, _, secret = _settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录管理后台")
    token = authorization[7:].strip()
    try:
        token_user, expires, nonce, signature = token.split(":", 3)
        payload = f"{token_user}:{expires}:{nonce}"
        valid = hmac.compare_digest(signature, _sign(payload, secret))
        valid = valid and int(expires) > int(time.time())
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(401, "管理登录已过期")
    if token_user == username:
        return token_user
    with connect() as db:
        row = db.execute("SELECT id FROM admins WHERE username=%s", (token_user,)).fetchone()
    if not row:
        raise HTTPException(401, "管理员账号不存在或已被移除")
    return token_user


def admin_role(token_user: str) -> str:
    env_user, _, _ = _settings()
    if token_user == env_user:
        return "superadmin"
    with connect() as db:
        row = db.execute("SELECT role FROM admins WHERE username=%s", (token_user,)).fetchone()
    if not row:
        raise HTTPException(401, "管理员账号不存在或已被移除")
    return row["role"]


def require_superadmin(admin: str = Depends(current_admin)) -> str:
    if admin_role(admin) != "superadmin":
        raise HTTPException(403, "需要超级管理员权限")
    return admin


@router.post("/login")
def admin_login(payload: AdminLoginIn, request: Request):
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = admin_login_limiter.hit(client)
    if not allowed:
        raise HTTPException(429, "登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    username, password, _ = _settings()
    # 优先匹配系统环境变量根管理员
    if hmac.compare_digest(payload.username, username) and hmac.compare_digest(payload.password, password):
        return {"token": issue_token(username), "username": username}
    # 匹配数据库管理员账号
    with connect() as db:
        admin_row = db.execute("SELECT * FROM admins WHERE username=%s", (payload.username,)).fetchone()
    if admin_row and verify_password(payload.password, admin_row["password_hash"]):
        return {"token": issue_token(admin_row["username"]), "username": admin_row["username"]}
    raise HTTPException(401, "账号或密码错误")


@router.get("/overview")
def overview(_: str = Depends(current_admin)):
    with connect() as db:
        totals = db.execute("""SELECT
            (SELECT COUNT(*) FROM users) AS users,
            (SELECT COUNT(*) FROM users WHERE last_login_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') AS active_users,
            (SELECT COUNT(*) FROM schedules) AS schedules,
            (SELECT COUNT(*) FROM feedbacks WHERE status IN ('pending','processing')) AS open_feedback,
            (SELECT COUNT(*) FROM user_identities) AS agent_bindings""").fetchone()
        traffic = db.execute("""SELECT COUNT(*) AS requests,
            COUNT(*) FILTER (WHERE status >= 500) AS errors,
            COALESCE(ROUND(AVG(duration_ms)),0) AS avg_ms,
            COALESCE(ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)),0) AS p95_ms
            FROM api_request_logs WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'""").fetchone()
        feedback = db.execute("SELECT status,COUNT(*) AS count FROM feedbacks GROUP BY status ORDER BY status").fetchall()
    requests = int(traffic["requests"] or 0)
    errors = int(traffic["errors"] or 0)
    return {"totals": dict(totals), "traffic": {**dict(traffic),
        "error_rate": round(errors * 100 / requests, 2) if requests else 0},
        "feedback": {row["status"]: row["count"] for row in feedback},
        "generated_at": datetime.now(UTC).isoformat()}


@router.get("/traffic")
def traffic(hours: int = Query(default=24, ge=1, le=168), _: str = Depends(current_admin)):
    with connect() as db:
        timeline = db.execute("""SELECT date_trunc('hour',created_at) AS bucket,COUNT(*) AS requests,
            COUNT(*) FILTER (WHERE status >= 500) AS errors,ROUND(AVG(duration_ms)) AS avg_ms
            FROM api_request_logs WHERE created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
            GROUP BY bucket ORDER BY bucket""", (hours,)).fetchall()
        paths = db.execute("""SELECT path,COUNT(*) AS requests,
            COUNT(*) FILTER (WHERE status >= 400) AS failures,ROUND(AVG(duration_ms)) AS avg_ms,
            MAX(duration_ms) AS max_ms FROM api_request_logs
            WHERE created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
            GROUP BY path ORDER BY requests DESC LIMIT 12""", (hours,)).fetchall()
        errors = db.execute("""SELECT method,path,status,duration_ms,created_at FROM api_request_logs
            WHERE status >= 400 AND created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
            ORDER BY created_at DESC LIMIT 30""", (hours,)).fetchall()
    return {"timeline": [row_dict(row) for row in timeline], "paths": [dict(row) for row in paths],
            "recent_errors": [row_dict(row) for row in errors]}


@router.get("/feedback")
def feedback_list(status: str = "", category: str = "", search: str = "",
                  limit: int = Query(default=100, ge=1, le=200), _: str = Depends(current_admin)):
    clauses, params = [], []
    if status:
        if status not in FEEDBACK_STATUSES:
            raise HTTPException(400, "反馈状态不正确")
        clauses.append("f.status=%s")
        params.append(status)
    if category:
        clauses.append("f.category=%s")
        params.append(category)
    if search.strip():
        clauses.append("(f.description ILIKE %s OR f.contact ILIKE %s OR CAST(f.id AS TEXT)=%s)")
        needle = f"%{search.strip()}%"
        params.extend([needle, needle, search.strip()])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        rows = db.execute(f"""SELECT f.*,s.name AS schedule_name,s.term AS schedule_term
            FROM feedbacks f LEFT JOIN schedules s ON s.id=f.schedule_id {where}
            ORDER BY f.created_at DESC LIMIT %s""", (*params, limit)).fetchall()
    result = []
    for row in rows:
        item = row_dict(row)
        item["feedback_no"] = feedback_number(item["id"], item["created_at"])
        item["category_label"] = CATEGORY_LABELS.get(item["category"], "其他")
        result.append(item)
    return result


@router.patch("/feedback/{feedback_id}")
def update_feedback(feedback_id: int, payload: FeedbackUpdateIn, admin: str = Depends(current_admin)):
    with connect() as db:
        row = db.execute("""UPDATE feedbacks SET status=%s,admin_note=%s,updated_at=CURRENT_TIMESTAMP
            WHERE id=%s RETURNING *""", (payload.status, payload.admin_note.strip(), feedback_id)).fetchone()
        if not row:
            raise HTTPException(404, "反馈不存在")
        db.execute("""INSERT INTO admin_audit_logs(admin_name,action,target_type,target_id,details)
            VALUES(%s,'feedback.update','feedback',%s,%s::jsonb)""",
            (admin, str(feedback_id), json.dumps({"status": payload.status}, ensure_ascii=False)))
    item = row_dict(row)
    item["feedback_no"] = feedback_number(item["id"], item["created_at"])
    return item


@router.get("/audit")
def audit_logs(limit: int = Query(default=50, ge=1, le=200), _: str = Depends(current_admin)):
    with connect() as db:
        rows = db.execute("SELECT * FROM admin_audit_logs ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [row_dict(row) for row in rows]


@router.get("/llm-configs")
def llm_configs(_: str = Depends(current_admin)):
    return [public_config(scope) for scope in SCOPES]


@router.put("/llm-configs/{scope}")
def update_llm_config(scope: str, payload: LlmConfigIn, admin: str = Depends(require_superadmin)):
    if scope not in SCOPES:
        raise HTTPException(404, "LLM 配置分组不存在")
    if payload.base_url and not payload.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "接口地址必须以 http:// 或 https:// 开头")
    try:
        result = save_llm_config(scope, payload.model_dump(), payload.api_key, payload.clear_api_key)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    with connect() as db:
        db.execute("""INSERT INTO admin_audit_logs(admin_name,action,target_type,target_id,details)
            VALUES(%s,'llm_config.update','llm_config',%s,%s::jsonb)""",
            (admin, scope, json.dumps({"model": payload.model, "base_url": payload.base_url}, ensure_ascii=False)))
    return result


@router.post("/llm-configs/{scope}/test")
def test_config(scope: str, payload: LlmTestIn = LlmTestIn(), _: str = Depends(current_admin)):
    if scope not in SCOPES:
        raise HTTPException(404, "LLM 配置分组不存在")
    if payload.base_url and not payload.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "接口地址必须以 http:// 或 https:// 开头")
    return test_llm_connection(
        scope=scope,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        timeout_seconds=payload.timeout_seconds,
        enable_thinking=payload.enable_thinking,
    )


@router.delete("/llm-configs/{scope}")
def reset_config(scope: str, admin: str = Depends(require_superadmin)):
    if scope not in SCOPES:
        raise HTTPException(404, "LLM 配置分组不存在")
    result = reset_llm_config(scope)
    with connect() as db:
        db.execute("""INSERT INTO admin_audit_logs(admin_name,action,target_type,target_id,details)
            VALUES(%s,'llm_config.reset','llm_config',%s,'{}'::jsonb)""", (admin, scope))
    return result


@router.get("/admins")
def list_admins(_: str = Depends(current_admin)):
    env_user, _, _ = _settings()
    with connect() as db:
        rows = db.execute("SELECT id, username, role, created_by, created_at FROM admins ORDER BY created_at ASC").fetchall()
    result = []
    has_env = any(row["username"] == env_user for row in rows)
    if not has_env:
        result.append({
            "id": 0,
            "username": env_user,
            "role": "superadmin",
            "created_by": "system",
            "created_at": None,
            "is_system_root": True,
        })
    for row in rows:
        item = row_dict(row)
        item["is_system_root"] = (item["username"] == env_user)
        result.append(item)
    return result


@router.post("/admins")
def create_admin(payload: AdminCreateIn, admin: str = Depends(require_superadmin)):
    env_user, _, _ = _settings()
    if payload.username.lower() == env_user.lower():
        raise HTTPException(400, "该用户名与系统根管理员冲突")
    pwd_hash = hash_password(payload.password)
    try:
        with connect() as db:
            row = db.execute(
                """INSERT INTO admins(username, password_hash, role, created_by)
                   VALUES(%s, %s, %s, %s) RETURNING id, username, role, created_by, created_at""",
                (payload.username, pwd_hash, payload.role, admin),
            ).fetchone()
            db.execute(
                """INSERT INTO admin_audit_logs(admin_name, action, target_type, target_id, details)
                   VALUES(%s, 'admin.create', 'admin', %s, %s::jsonb)""",
                (admin, payload.username, json.dumps({"role": payload.role}, ensure_ascii=False)),
            )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(400, "该管理员账号已存在")
        raise
    item = row_dict(row)
    item["is_system_root"] = False
    return item


@router.delete("/admins/{admin_id}")
def delete_admin(admin_id: int, admin: str = Depends(require_superadmin)):
    if admin_id == 0:
        raise HTTPException(400, "禁止删除系统根管理员")
    with connect() as db:
        target = db.execute("SELECT * FROM admins WHERE id=%s", (admin_id,)).fetchone()
        if not target:
            raise HTTPException(404, "管理员不存在")
        if target["username"] == admin:
            raise HTTPException(400, "不能删除当前正在登录的管理员账号")
        db.execute("DELETE FROM admins WHERE id=%s", (admin_id,))
        db.execute(
            """INSERT INTO admin_audit_logs(admin_name, action, target_type, target_id, details)
               VALUES(%s, 'admin.delete', 'admin', %s, %s::jsonb)""",
            (admin, target["username"], json.dumps({"id": admin_id}, ensure_ascii=False)),
        )
    return {"ok": True, "deleted_username": target["username"]}


# ==================== 用户与课表管理 ====================

@router.get("/users")
def list_users(
    search: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 20,
    limit: int = 20,
    offset: int = 0,
    _: str = Depends(current_admin),
):
    """用户检索列表（支持 ID / 邮箱 / 用户名 / OpenID 搜索）。"""
    kw = (search or query).strip()
    if offset > 0 or limit != 20:
        effective_limit = limit
        effective_offset = offset
    else:
        effective_limit = page_size
        effective_offset = (page - 1) * page_size

    clauses, params = [], []
    if kw:
        clauses.append("(CAST(u.id AS TEXT) = %s OR u.email ILIKE %s OR u.username ILIKE %s OR u.openid ILIKE %s)")
        params.extend([kw, f"%{kw}%", f"%{kw}%", f"%{kw}%"])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as db:
        total_row = db.execute(f"SELECT COUNT(*) AS total FROM users u {where}", params).fetchone()
        total = int(total_row["total"]) if total_row else 0

        rows = db.execute(f"""
            SELECT u.id, u.openid, u.email, u.username, u.created_at, u.last_login_at,
                   (SELECT COUNT(*) FROM schedules s WHERE s.user_id = u.id) AS schedule_count,
                   (SELECT COALESCE(array_to_json(array_agg(ui.provider)), '[]'::json) FROM user_identities ui WHERE ui.user_id = u.id) AS providers
            FROM users u
            {where}
            ORDER BY u.id DESC
            LIMIT %s OFFSET %s
        """, (*params, effective_limit, effective_offset)).fetchall()

    users = []
    for r in rows:
        item = row_dict(r)
        item["providers"] = r.get("providers") or []
        users.append(item)

    return {
        "total": total,
        "page": page,
        "page_size": effective_limit,
        "users": users,
        "items": users,
    }


@router.get("/users/{user_id}/detail")
def user_detail(user_id: int, _: str = Depends(current_admin)):
    """获取指定用户的名下课表与绑定渠道详情。"""
    with connect() as db:
        user = db.execute("SELECT id, openid, email, username, created_at, last_login_at FROM users WHERE id=%s", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")

        schedules = db.execute("""
            SELECT s.id, s.name, s.term, s.start_date, s.end_date, s.created_at,
                   (SELECT COUNT(*) FROM courses c WHERE c.schedule_id = s.id) AS course_count
            FROM schedules s
            WHERE s.user_id = %s
            ORDER BY s.id DESC
        """, (user_id,)).fetchall()

        identities = db.execute("""
            SELECT id, provider, provider_user_id, last_seen_at
            FROM user_identities
            WHERE user_id = %s
            ORDER BY id ASC
        """, (user_id,)).fetchall()

        bots = db.execute("""
            SELECT account_id, provider, status, error_message, updated_at
            FROM channel_accounts
            WHERE owner_user_id = %s
            ORDER BY id ASC
        """, (user_id,)).fetchall()

    return {
        "user": row_dict(user),
        "schedules": [row_dict(s) for s in schedules],
        "identities": [row_dict(i) for i in identities],
        "bots": [row_dict(b) for b in bots],
    }


get_user_detail = user_detail



@router.get("/users/{user_id}/schedules/{schedule_id}/courses")
def schedule_courses(user_id: int, schedule_id: int, _: str = Depends(current_admin)):
    """获取用户某张课表的所有课程明细。"""
    with connect() as db:
        sched = db.execute("SELECT id, name, term, start_date, end_date FROM schedules WHERE id=%s AND user_id=%s", (schedule_id, user_id)).fetchone()
        if not sched:
            raise HTTPException(404, "课表不存在或不属于该用户")

        courses = db.execute("""
            SELECT id, name, teacher, room, weekday, start_section, end_section, weeks, color
            FROM courses
            WHERE schedule_id = %s
            ORDER BY weekday, start_section
        """, (schedule_id,)).fetchall()

    return {
        "schedule": row_dict(sched),
        "courses": [row_dict(c) for c in courses],
    }


get_schedule_courses = schedule_courses


@router.post("/users/{user_id}/unbind-wechat")
def admin_unbind_wechat(user_id: int, admin: str = Depends(require_superadmin)):
    """管理员一键解绑用户的微信（解除死锁并吊销旧会话）。"""
    with connect() as db:
        user = db.execute("SELECT id, openid, email FROM users WHERE id=%s", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        if not user["openid"]:
            raise HTTPException(400, "该用户未绑定微信")

        from ..services.account_link import unlink_wechat
        unlink_wechat(db, user_id)

        db.execute(
            """INSERT INTO admin_audit_logs(admin_name, action, target_type, target_id, details)
               VALUES(%s, 'user.unbind_wechat', 'user', %s, %s::jsonb)""",
            (admin, str(user_id), json.dumps({"openid": user["openid"]}, ensure_ascii=False)),
        )

    return {"ok": True, "message": "微信绑定已解除，对应小程序会话已同步注销"}


# ==================== 系统与缓存运维 ====================

class ClearRateLimitIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)


class ClearSessionIn(BaseModel):
    user_id: int = Field(gt=0)


@router.get("/system/status")
def system_status(_: str = Depends(current_admin)):
    """获取 Redis 运行状态指标与微信 Bot 账号状态。"""
    from ..redis import get_redis

    redis_info = {
        "connected": False,
        "used_memory_human": "-",
        "connected_clients": 0,
        "total_keys": 0,
        "version": "-",
        "uptime_days": 0,
    }

    client = get_redis()
    if client:
        try:
            info = client.info()
            dbsize = client.dbsize()
            redis_info = {
                "connected": True,
                "used_memory_human": info.get("used_memory_human", "-"),
                "connected_clients": info.get("connected_clients", 0),
                "total_keys": dbsize,
                "version": info.get("redis_version", "-"),
                "uptime_days": info.get("uptime_in_days", 0),
            }
        except Exception as exc:
            redis_info["error"] = str(exc)

    with connect() as db:
        bots = db.execute("""
            SELECT account_id, provider, owner_user_id, status, error_message, updated_at
            FROM channel_accounts
            ORDER BY updated_at DESC
        """).fetchall()

    return {
        "redis": redis_info,
        "bots": [row_dict(b) for b in bots],
        "server_time": datetime.now(UTC).isoformat(),
    }


@router.post("/system/redis/clear-ratelimit")
def clear_ratelimit(payload: ClearRateLimitIn, admin: str = Depends(current_admin)):
    """清除指定 IP 或用户标识的限流计数。"""
    from ..redis import get_redis
    client = get_redis()
    if not client:
        return {"ok": True, "deleted_count": 0, "note": "Redis 未配置或处于内存降级模式"}

    target = payload.key.strip()
    if "*" in target:
        patterns = [target]
    else:
        patterns = [
            f"xushi:ratelimit:*{target}*",
            f"xushi:ratelimit:{target}",
            f"*{target}*",
        ]
    deleted = 0
    try:
        found_keys = set()
        for p in patterns:
            for k in client.scan_iter(match=p, count=200):
                found_keys.add(k)
        if found_keys:
            deleted = client.delete(*found_keys)
    except Exception as exc:
        raise HTTPException(500, f"清理限流缓存异常: {exc}")

    return {"ok": True, "deleted_count": deleted, "key": target}


@router.post("/system/redis/clear-session")
def clear_user_sessions(payload: ClearSessionIn, admin: str = Depends(current_admin)):
    """清除指定用户的 Redis 会话缓存（强制重新鉴权）。"""
    from ..auth.deps import invalidate_session_cache
    with connect() as db:
        sessions = db.execute("SELECT token_hash FROM sessions WHERE user_id=%s", (payload.user_id,)).fetchall()
        for s in sessions:
            invalidate_session_cache(token_digest=s["token_hash"])

    return {"ok": True, "cleared_count": len(sessions), "user_id": payload.user_id}

