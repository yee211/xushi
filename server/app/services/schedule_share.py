"""课表分享码服务：生成分享提取码、解析预览与跨用户导入。"""
import secrets
from datetime import UTC, datetime, timedelta

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ShareError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def create_or_get_share_code(db, user_id: int, schedule_id: int, ttl_days: int = 7) -> dict:
    """为指定课表生成 6 位提取码，若已有 1 小时以上有效期的口令则直接复用。"""
    sched = db.execute("SELECT id, name, term FROM schedules WHERE id=%s AND user_id=%s",
                       (schedule_id, user_id)).fetchone()
    if not sched:
        raise ShareError("NOT_FOUND", "课表不存在或无权分享")

    # 查验当前是否已有仍在有效期的口令（且剩余时间大于 1 小时）
    active = db.execute("""
        SELECT code, expires_at FROM schedule_share_codes
        WHERE schedule_id=%s AND user_id=%s AND expires_at > CURRENT_TIMESTAMP + INTERVAL '1 hour'
        ORDER BY id DESC LIMIT 1
    """, (schedule_id, user_id)).fetchone()

    if active:
        return {
            "code": active["code"],
            "expires_at": active["expires_at"],
            "schedule_id": sched["id"],
            "schedule_name": sched["name"],
            "reused": True,
        }

    expires = datetime.now(UTC) + timedelta(days=max(1, min(ttl_days, 30)))
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        inserted = db.execute("""
            INSERT INTO schedule_share_codes(code, schedule_id, user_id, expires_at)
            VALUES(%s, %s, %s, %s)
            ON CONFLICT(code) DO NOTHING RETURNING id
        """, (code, schedule_id, user_id, expires)).fetchone()
        if inserted:
            return {
                "code": code,
                "expires_at": expires,
                "schedule_id": sched["id"],
                "schedule_name": sched["name"],
                "reused": False,
            }

    raise ShareError("GENERATE_FAILED", "生成分享码失败，请重试")


def get_share_info(db, code: str) -> dict:
    """根据分享码查询课表概要预览信息。"""
    normalized = str(code or "").strip().upper()
    if len(normalized) != 6:
        raise ShareError("INVALID_FORMAT", "分享码格式不正确（需6位字母数字）")

    row = db.execute("""
        SELECT c.code, c.schedule_id, c.user_id, c.expires_at,
               s.name AS schedule_name, s.term, s.start_date, s.end_date,
               u.username, u.email
        FROM schedule_share_codes c
        LEFT JOIN schedules s ON s.id = c.schedule_id
        LEFT JOIN users u ON u.id = c.user_id
        WHERE c.code = %s
    """, (normalized,)).fetchone()

    if not row:
        raise ShareError("NOT_FOUND", "分享码不存在，请确认后重试")
    if row["expires_at"] <= datetime.now(UTC):
        raise ShareError("EXPIRED", "该分享码已过期失效")
    if not row["schedule_name"]:
        raise ShareError("DELETED", "该分享课表已被原作者删除")

    course_row = db.execute("SELECT COUNT(*) AS count FROM courses WHERE schedule_id=%s",
                            (row["schedule_id"],)).fetchone()
    course_count = int(course_row["count"]) if course_row else 0

    return {
        "code": row["code"],
        "schedule_id": row["schedule_id"],
        "name": row["schedule_name"],
        "term": row["term"] or "",
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "course_count": course_count,
        "creator_user_id": row["user_id"],
        "creator_name": row["username"] or (row["email"].split("@")[0] if row["email"] else "同学"),
        "expires_at": row["expires_at"],
    }


def import_shared_schedule(db, user_id: int, code: str, custom_name: str | None = None) -> dict:
    """通过分享码将课表及课程复制克隆至接收者名下。"""
    info = get_share_info(db, code)
    if info["creator_user_id"] == user_id:
        raise ShareError("SELF_IMPORT", "这是你自己的课表，无需重复导入")

    src_id = info["schedule_id"]
    src_sched = db.execute(
        "SELECT id, name, term, start_date, end_date, background, variant_type FROM schedules WHERE id=%s",
        (src_id,)
    ).fetchone()
    if not src_sched:
        raise ShareError("DELETED", "该分享课表已被原作者删除")

    target_name = (custom_name or "").strip() or info["name"]
    # 查验重名，如果已有同名课表则增加 (导入) 后缀
    dup = db.execute("SELECT id FROM schedules WHERE user_id=%s AND name=%s LIMIT 1",
                     (user_id, target_name)).fetchone()
    if dup:
        target_name = f"{target_name} (导入)"

    new_sched = db.execute("""
        INSERT INTO schedules(user_id, name, term, start_date, end_date, background, variant_type)
        VALUES(%s, %s, %s, %s, %s, %s, 'original') RETURNING id
    """, (
        user_id, target_name, src_sched["term"], src_sched["start_date"],
        src_sched["end_date"], src_sched.get("background") or ""
    )).fetchone()

    new_id = new_sched["id"]

    # 纯 SQL 流式复制课程，保留原生 JSONB 格式
    db.execute("""
        INSERT INTO courses(schedule_id, name, teacher, room, weekday, start_section, end_section, weeks, color)
        SELECT %s, name, teacher, room, weekday, start_section, end_section, weeks, color
        FROM courses WHERE schedule_id=%s
    """, (new_id, src_id))

    count_row = db.execute("SELECT COUNT(*) AS count FROM courses WHERE schedule_id=%s",
                           (new_id,)).fetchone()
    courses_imported = int(count_row["count"]) if count_row else 0

    return {
        "schedule_id": new_id,
        "name": target_name,
        "term": src_sched["term"] or "",
        "courses_imported": courses_imported,
    }
