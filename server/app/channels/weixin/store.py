"""Encrypted iLink credentials and durable polling/message state."""
import base64
import hashlib
import os

from Crypto.Cipher import AES

from .protocol import Credentials


def credential_key() -> bytes:
    raw = os.getenv("WEIXIN_ILINK_CREDENTIAL_KEY", "").strip()
    if not raw:
        raise RuntimeError("缺少 WEIXIN_ILINK_CREDENTIAL_KEY")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as error:
        raise RuntimeError("WEIXIN_ILINK_CREDENTIAL_KEY 不是合法 Base64") from error
    if len(key) != 32:
        raise RuntimeError("WEIXIN_ILINK_CREDENTIAL_KEY 解码后必须为 32 字节")
    return key


def encrypt_token(token: str) -> str:
    cipher = AES.new(credential_key(), AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(token.encode())
    return base64.urlsafe_b64encode(cipher.nonce + tag + ciphertext).decode()


def decrypt_token(value: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(value)
        nonce, tag, ciphertext = payload[:16], payload[16:32], payload[32:]
        return AES.new(credential_key(), AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ciphertext, tag).decode()
    except (ValueError, UnicodeDecodeError) as error:
        raise RuntimeError("微信 iLink 凭证无法解密") from error


def save_account(db, credentials: Credentials, owner_user_id: int | None = None) -> None:
    db.execute("""INSERT INTO channel_accounts(
        provider,account_id,bot_token_encrypted,api_base_url,admin_user_id,owner_user_id)
        VALUES('weixin_ilink',%s,%s,%s,%s,%s) ON CONFLICT(provider,account_id) DO UPDATE SET
        bot_token_encrypted=EXCLUDED.bot_token_encrypted,api_base_url=EXCLUDED.api_base_url,
        admin_user_id=EXCLUDED.admin_user_id,owner_user_id=COALESCE(EXCLUDED.owner_user_id,channel_accounts.owner_user_id),
        status='active',updated_at=CURRENT_TIMESTAMP""",
        (credentials.account_id, encrypt_token(credentials.bot_token), credentials.base_url,
         credentials.admin_user_id, owner_user_id))


def load_accounts(db) -> list[tuple[Credentials, str, str]]:
    """活跃账号列表：(凭证, 游标, token 指纹)。指纹用于检测重新扫码后的 token 轮换。"""
    rows = db.execute("""SELECT account_id,bot_token_encrypted,api_base_url,admin_user_id,update_cursor
        FROM channel_accounts WHERE provider='weixin_ilink' AND status='active' ORDER BY id""").fetchall()
    accounts = []
    for row in rows:
        token = decrypt_token(row["bot_token_encrypted"])
        fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
        accounts.append((Credentials(row["account_id"], token, row["api_base_url"],
                                     row["admin_user_id"] or ""), row["update_cursor"] or "", fingerprint))
    return accounts


def save_cursor(db, account_id: str, cursor: str) -> None:
    if cursor:
        db.execute("""UPDATE channel_accounts SET update_cursor=%s,updated_at=CURRENT_TIMESTAMP
            WHERE provider='weixin_ilink' AND account_id=%s""", (cursor, account_id))


def claim_message(db, account_id: str, message_id: str) -> bool:
    row = db.execute("""INSERT INTO channel_messages(provider,account_id,message_id,status)
        VALUES('weixin_ilink',%s,%s,'processing') ON CONFLICT(provider,account_id,message_id) DO NOTHING
        RETURNING message_id""", (account_id, message_id)).fetchone()
    if not row:
        row = db.execute("""UPDATE channel_messages SET status='processing',error='',processed_at=NULL,
            received_at=CURRENT_TIMESTAMP
            WHERE provider='weixin_ilink' AND account_id=%s AND message_id=%s
            AND (status='failed' OR (status='processing' AND received_at<CURRENT_TIMESTAMP-INTERVAL '5 minutes'))
            RETURNING message_id""", (account_id, message_id)).fetchone()
    return bool(row)


def reset_stale_processing(db) -> int:
    """崩溃恢复：把上次运行遗留的 processing 消息标记为失败。

    游标在消息完成后才保存，worker 崩溃即游标未推进，重启后 iLink 会按旧游标重投递；
    置为 failed 让 claim_message 立即可重新领取，避免消息卡在 processing
    被当成已处理而随游标推进一起丢失。
    """
    rows = db.execute("""UPDATE channel_messages SET status='failed',
        error='worker 上次运行未完成', received_at=CURRENT_TIMESTAMP
        WHERE provider='weixin_ilink' AND status='processing' RETURNING message_id""").fetchall()
    return len(rows)


def complete_message(db, account_id: str, message_id: str, error: str = "") -> None:
    db.execute("""UPDATE channel_messages SET status=%s,error=%s,processed_at=CURRENT_TIMESTAMP
        WHERE provider='weixin_ilink' AND account_id=%s AND message_id=%s""",
        ("failed" if error else "done", error[:1000], account_id, message_id))
