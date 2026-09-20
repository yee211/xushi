"""One-time channel binding codes and identity mappings."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

class BindingError(RuntimeError):
    pass

def _digest(code: str) -> str:
    return hashlib.sha256(code.upper().encode()).hexdigest()

def find_active_code(db, code: str, provider: str) -> dict | None:
    """按明文码查询有效绑定码（存在、未消费、未过期），无效返回 None。"""
    row = db.execute("SELECT * FROM identity_binding_codes WHERE code_hash=%s AND provider=%s",
                     (_digest(code), provider)).fetchone()
    if not row or row["consumed_at"] or row["expires_at"] <= datetime.now(UTC):
        return None
    return row

def create_binding_code(db, user_id: int, provider: str, ttl_seconds: int = 300) -> tuple[str, datetime]:
    db.execute("""UPDATE identity_binding_codes SET consumed_at=CURRENT_TIMESTAMP
        WHERE user_id=%s AND provider=%s AND consumed_at IS NULL""", (user_id, provider))
    expires = datetime.now(UTC) + timedelta(seconds=max(60, min(ttl_seconds, 1800)))
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        inserted = db.execute("""INSERT INTO identity_binding_codes(code_hash,user_id,provider,expires_at)
            VALUES(%s,%s,%s,%s) ON CONFLICT(code_hash) DO NOTHING RETURNING id""",
            (_digest(code), user_id, provider, expires)).fetchone()
        if inserted:
            return code, expires
    raise BindingError("绑定码生成失败，请重试")

def consume_binding_code(db, code: str, provider: str, provider_user_id: str,
                         account_id: str = "") -> int:
    normalized = str(code or "").strip().upper()
    if len(normalized) != 6:
        raise BindingError("绑定码格式不正确")
    row = db.execute("""SELECT * FROM identity_binding_codes WHERE code_hash=%s AND provider=%s FOR UPDATE""",
                     (_digest(normalized), provider)).fetchone()
    if not row:
        raise BindingError("绑定码无效")
    if row["consumed_at"] or row["expires_at"] <= datetime.now(UTC):
        raise BindingError("绑定码已失效，请在小程序中重新生成")
    if row["attempt_count"] >= 5:
        raise BindingError("绑定尝试次数过多，请重新生成绑定码")
    existing = db.execute("SELECT user_id FROM user_identities WHERE provider=%s AND provider_user_id=%s",
                          (provider, provider_user_id)).fetchone()
    if existing and existing["user_id"] != row["user_id"]:
        # 该渠道身份已绑到其他账号（常见于解绑后重绑、账号迁移等场景）。
        # 发送者主动提交新绑定码，视为授权切换：先删旧绑定，继续完成新绑定；
        # 无需计入 attempt_count，此处无法被第三方利用（只有发送者本人才能以此 sender_id 发消息）。
        db.execute("DELETE FROM user_identities WHERE provider=%s AND provider_user_id=%s",
                   (provider, provider_user_id))
    db.execute("DELETE FROM user_identities WHERE user_id=%s AND provider=%s AND provider_user_id<>%s",
               (row["user_id"], provider, provider_user_id))
    if account_id:
        db.execute("""INSERT INTO user_identities(user_id,provider,provider_user_id,account_id)
            VALUES(%s,%s,%s,%s) ON CONFLICT(provider,provider_user_id) DO UPDATE SET
            user_id=EXCLUDED.user_id,account_id=EXCLUDED.account_id,last_seen_at=CURRENT_TIMESTAMP""",
            (row["user_id"], provider, provider_user_id, account_id))
    else:
        db.execute("""INSERT INTO user_identities(user_id,provider,provider_user_id)
            VALUES(%s,%s,%s) ON CONFLICT(provider,provider_user_id) DO UPDATE SET
            user_id=EXCLUDED.user_id,last_seen_at=CURRENT_TIMESTAMP""",
            (row["user_id"], provider, provider_user_id))
    db.execute("UPDATE identity_binding_codes SET consumed_at=CURRENT_TIMESTAMP WHERE id=%s", (row["id"],))
    return row["user_id"]

def unbind_provider_identity(db, provider: str, provider_user_id: str) -> int:
    """渠道侧解绑：按 provider_user_id 移除映射，返回删除行数。"""
    return db.execute("DELETE FROM user_identities WHERE provider=%s AND provider_user_id=%s",
                      (provider, provider_user_id)).rowcount
