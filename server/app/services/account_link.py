"""账号互通：微信小程序账号绑定已有邮箱账号（安卓/网页端）。

users 表同一行可同时持有 email 与 openid，绑定即把 openid 写到邮箱账号行，
并把小程序侧空壳账号的会话、课表、渠道身份等数据并入后删除——此后三端
（App/网页/小程序/微信助手）共享同一 user_id，课表天然一致，无需同步。
"""
from datetime import datetime

from ..auth.deps import invalidate_session_cache
from .binding import create_binding_code, find_active_code

PROVIDER = "wechat_miniprogram"


class AccountLinkError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def create_link_code(db, user_id: int, ttl_seconds: int = 300) -> tuple[str, datetime]:
    """为邮箱账号生成小程序绑定码；已绑定微信的账号需先解绑。"""
    row = db.execute("SELECT openid FROM users WHERE id=%s", (user_id,)).fetchone()
    if row is None:
        raise AccountLinkError("NOT_FOUND", "账号不存在")
    if row["openid"]:
        raise AccountLinkError("ALREADY_BOUND", "该账号已绑定微信，请先解除绑定")
    return create_binding_code(db, user_id, PROVIDER, ttl_seconds)


def _overlaps(a: dict, b: dict) -> bool:
    """判定两份课表的学期日期范围是否重叠（无 end_date 视为无限延续）。"""
    if not a["start_date"] or not b["start_date"]:
        return False
    if a["end_date"] is not None and a["end_date"] < b["start_date"]:
        return False
    if b["end_date"] is not None and b["end_date"] < a["start_date"]:
        return False
    return True


def link_wechat_account(db, code: str, wx_user: dict) -> dict:
    """校验绑定码，把小程序账号（wx_user，须含 openid）并入邮箱账号。

    会话改指向目标账号（小程序令牌保持登录态）、渠道身份与反馈随迁、
    channel_accounts 归属改写；课表仅搬迁与目标账号学期不重叠的，
    重叠的（多为小程序侧演示/Excel 重复导入）直接丢弃，避免合并后
    同一日期命中多张课表使查询产生歧义。整个操作在调用方的事务内执行。
    """
    openid = str(wx_user.get("openid") or "").strip()
    if not openid:
        raise AccountLinkError("NO_OPENID", "请在微信小程序中操作")
    if wx_user.get("email"):
        raise AccountLinkError("WX_HAS_EMAIL", "当前微信已绑定过账号，请先解除绑定后再操作")
    normalized = str(code or "").strip().upper()
    row = find_active_code(db, normalized, PROVIDER) if len(normalized) == 6 else None
    if row is None:
        raise AccountLinkError("INVALID_CODE", "绑定码无效或已过期，请在 App 中重新生成")

    wx_id, target_id = wx_user["id"], row["user_id"]
    if target_id == wx_id:
        raise AccountLinkError("SELF_BIND", "当前账号无需与自己绑定")
    target = db.execute("SELECT id, openid, email, username FROM users WHERE id=%s FOR UPDATE",
                        (target_id,)).fetchone()
    if target is None:
        raise AccountLinkError("INVALID_CODE", "绑定码无效或已过期，请在 App 中重新生成")
    if target["openid"]:
        raise AccountLinkError("TARGET_BOUND", "该账号已绑定其他微信，请先在 App 端解除绑定")

    # 会话随迁：小程序当前令牌在合并后继续有效，无需重新登录
    moved_sessions = db.execute("SELECT token_hash FROM sessions WHERE user_id=%s", (wx_id,)).fetchall()
    sessions_moved = db.execute("UPDATE sessions SET user_id=%s WHERE user_id=%s",
                                (target_id, wx_id)).rowcount
    # 渠道身份随迁：微信助手/企业微信的绑定关系转挂到目标账号（同渠道先解旧再挂新）
    agent_bindings_moved = 0
    wx_identities = db.execute("SELECT id, provider FROM user_identities WHERE user_id=%s",
                               (wx_id,)).fetchall()
    for identity in wx_identities:
        # 仅当 wx_id 持有该 provider 的 identity 时，才删除 target 上可能存在的旧记录，
        # 否则 target 自己独立绑定的 ClawBot 等渠道会被误删（Bug：target 原有绑定丢失）
        db.execute("DELETE FROM user_identities WHERE user_id=%s AND provider=%s",
                   (target_id, identity["provider"]))
        agent_bindings_moved += db.execute("UPDATE user_identities SET user_id=%s WHERE id=%s",
                                           (target_id, identity["id"])).rowcount
    db.execute("UPDATE channel_accounts SET owner_user_id=%s WHERE owner_user_id=%s",
               (target_id, wx_id))
    db.execute("UPDATE feedbacks SET user_id=%s WHERE user_id=%s", (target_id, wx_id))
    db.execute("UPDATE identity_binding_codes SET user_id=%s WHERE user_id=%s AND consumed_at IS NULL",
               (target_id, wx_id))

    # 课表合并：与目标账号或已搬迁课表学期重叠的丢弃，其余搬迁——
    # 参照集随搬迁递增，小程序侧互相重叠的课表也只保留一张，
    # 避免合并后同一日期命中多张课表使查询产生歧义
    schedules_moved, schedules_discarded = 0, 0
    wx_schedules = db.execute("SELECT id, start_date, end_date FROM schedules WHERE user_id=%s",
                              (wx_id,)).fetchall()
    if wx_schedules:
        occupied = db.execute("SELECT start_date, end_date FROM schedules WHERE user_id=%s",
                              (target_id,)).fetchall()
        for schedule in wx_schedules:
            if any(_overlaps(schedule, other) for other in occupied):
                db.execute("DELETE FROM schedules WHERE id=%s", (schedule["id"],))
                schedules_discarded += 1
            else:
                db.execute("UPDATE schedules SET user_id=%s WHERE id=%s",
                           (target_id, schedule["id"]))
                occupied.append(dict(schedule))
                schedules_moved += 1

    # openid 带 UNIQUE 约束：先删小程序侧账号腾出 openid，再写到目标账号。
    # 有意不随迁的 users 外键表（行随本 DELETE 级联清除）：
    # daily_push_logs（晨推去重日志，纯运行记录，目标账号自有日志不受影响）、
    # schedule_sync_sessions（0007 的短时效同步会话，本就按 expires_at 过期）。
    # 新增带 users 外键的表时，需在此评估随迁或补充说明。
    db.execute("DELETE FROM users WHERE id=%s", (wx_id,))
    db.execute("UPDATE users SET openid=%s, last_login_at=CURRENT_TIMESTAMP WHERE id=%s",
               (openid, target_id))
    db.execute("UPDATE identity_binding_codes SET consumed_at=CURRENT_TIMESTAMP WHERE id=%s",
               (row["id"],))

    for s in moved_sessions:
        invalidate_session_cache(token_digest=s["token_hash"])

    return {"username": target["username"] or "", "email": target["email"] or "",
            "sessions_moved": sessions_moved, "schedules_moved": schedules_moved,
            "schedules_discarded": schedules_discarded,
            "agent_bindings_moved": agent_bindings_moved}


def unlink_wechat(db, user_id: int) -> dict:
    """解除账号与微信的绑定：
    1. 清空目标账号（App/邮箱）的 openid；
    2. 为独立微信小程序恢复/创建专属账号（以 openid 为准）；
    3. 将微信专属渠道身份（ClawBot weixin_ilink 与 wecom）、渠道账号（channel_accounts）、未消费绑定码转移至独立小程序账号；
    4. 课表保全：若独立微信账号下尚无课表，从原账号复制一份最新课表与课程，确保解绑后小程序与微信 ClawBot 仍可正常查课；
    5. 吊销原账号的小程序会话，小程序端静默重新登录即可无缝衔接独立微信账号，且 ClawBot 保持已绑定状态。
    """
    row = db.execute("SELECT openid FROM users WHERE id=%s", (user_id,)).fetchone()
    if row is None:
        raise AccountLinkError("NOT_FOUND", "账号不存在")
    if not row["openid"]:
        raise AccountLinkError("NOT_BOUND", "当前账号未绑定微信")
    openid = row["openid"]

    # 1. 解除目标账号上的 openid 绑定
    db.execute("UPDATE users SET openid=NULL WHERE id=%s", (user_id,))

    # 2. 为独立微信小程序恢复/创建专属账号
    wx_user = db.execute("""INSERT INTO users(openid) VALUES(%s)
        ON CONFLICT(openid) DO UPDATE SET last_login_at=CURRENT_TIMESTAMP
        RETURNING id""", (openid,)).fetchone()
    wx_id = wx_user["id"] if wx_user else None

    # 3. 微信专属渠道身份（ClawBot weixin_ilink 与 wecom）转移给独立微信账号
    agent_bindings_moved = 0
    if wx_id:
        for identity in db.execute(
            "SELECT id, provider FROM user_identities WHERE user_id=%s AND provider=ANY(%s)",
            (user_id, ["weixin_ilink", "wecom"])
        ).fetchall():
            db.execute("DELETE FROM user_identities WHERE user_id=%s AND provider=%s",
                       (wx_id, identity["provider"]))
            agent_bindings_moved += db.execute(
                "UPDATE user_identities SET user_id=%s WHERE id=%s",
                (wx_id, identity["id"])
            ).rowcount

        db.execute(
            "UPDATE channel_accounts SET owner_user_id=%s WHERE owner_user_id=%s AND provider='weixin_ilink'",
            (wx_id, user_id)
        )
        db.execute(
            "UPDATE identity_binding_codes SET user_id=%s WHERE user_id=%s AND provider=ANY(%s) AND consumed_at IS NULL",
            (wx_id, user_id, ["weixin_ilink", "wecom"])
        )

        # 4. 课表复制保全：若独立微信账号下无课表，复制一份 App 账号的课表，确保解绑后小程序有课表、ClawBot 查课正常
        wx_sched = db.execute("SELECT id FROM schedules WHERE user_id=%s LIMIT 1", (wx_id,)).fetchone()
        if not wx_sched:
            app_scheds = db.execute(
                "SELECT id, name, term, start_date, end_date, background, variant_type FROM schedules WHERE user_id=%s AND source_schedule_id IS NULL ORDER BY id ASC",
                (user_id,)
            ).fetchall()
            for sched in app_scheds:
                new_sched = db.execute(
                    """INSERT INTO schedules(user_id, name, term, start_date, end_date, background, variant_type)
                       VALUES(%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (wx_id, sched["name"], sched["term"], sched["start_date"], sched["end_date"], sched.get("background") or "", sched.get("variant_type") or "draft")
                ).fetchone()
                if new_sched:
                    db.execute(
                        """INSERT INTO courses(schedule_id, name, teacher, room, weekday, start_section, end_section, weeks, color)
                           SELECT %s, name, teacher, room, weekday, start_section, end_section, weeks, color
                           FROM courses WHERE schedule_id=%s""",
                        (new_sched["id"], sched["id"])
                    )

    # 5. 吊销原账号的小程序会话（小程序下次请求凭 openid 登录进入 wx_id）
    revoked_sessions = db.execute("SELECT token_hash FROM sessions WHERE user_id=%s", (user_id,)).fetchall()
    db.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    for s in revoked_sessions:
        invalidate_session_cache(token_digest=s["token_hash"])
    return {"wx_user_id": wx_id, "agent_bindings_moved": agent_bindings_moved}
