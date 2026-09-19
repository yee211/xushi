"""邮箱账号路由（网页端 / Android）：注册、登录、当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import create_token, get_current_user, hash_password, verify_password
from ..db import connect
from ..rate_limit import enforce_auth_rate_limit
from ..schemas import EmailLoginIn, RegisterIn

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register", status_code=201)
def register(payload: RegisterIn, request: Request):
    enforce_auth_rate_limit(request, "register")
    email = payload.email
    username = payload.username.strip()
    if len(username) < 2:
        raise HTTPException(400, "用户名至少需要 2 个字符")
    with connect() as db:
        if db.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
            raise HTTPException(409, "该邮箱已注册")
        if db.execute("SELECT 1 FROM users WHERE username=%s", (username,)).fetchone():
            raise HTTPException(409, "用户名已被占用")
        user = db.execute(
            "INSERT INTO users(email,username,password_hash) VALUES(%s,%s,%s) RETURNING id,email,username",
            (email, username, hash_password(payload.password)),
        ).fetchone()
        # 为新用户创建一个默认空课表，便于直接添加课程
        db.execute("INSERT INTO schedules(user_id,name,term) VALUES(%s,%s,%s)", (user["id"], "我的课表", ""))
    return {
        "token": create_token(user["id"], user["username"]),
        "user": {"id": user["id"], "email": user["email"], "username": user["username"]},
    }


@router.post("/login")
def login(payload: EmailLoginIn, request: Request):
    enforce_auth_rate_limit(request, "login")
    email = payload.email
    with connect() as db:
        user = db.execute(
            "SELECT id,email,username,password_hash FROM users WHERE email=%s", (email,)
        ).fetchone()
    if not user or not user["password_hash"] or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "邮箱或密码错误")
    return {
        "token": create_token(user["id"], user["username"]),
        "user": {"id": user["id"], "email": user["email"], "username": user["username"]},
    }


@router.get("/me")
def me(user=Depends(get_current_user)):
    with connect() as db:
        row = db.execute("SELECT id,email,username FROM users WHERE id=%s", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在")
    # 微信静默登录的用户没有邮箱/用户名，返回空串而不是 null，前端展示更稳
    return {"id": row["id"], "email": row["email"] or "", "username": row["username"] or ""}
