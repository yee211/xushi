"""Immutable message-to-sync mapping, independent of notification routing."""
SCHEMA = """CREATE TABLE IF NOT EXISTS academic_sync_requests (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,account_id TEXT NOT NULL,sender_id TEXT NOT NULL,message_id TEXT NOT NULL,
    job_id UUID NOT NULL REFERENCES academic_sync_jobs(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id,provider,account_id,sender_id,message_id))"""
BACKFILL = """INSERT INTO academic_sync_requests(user_id,provider,account_id,sender_id,message_id,job_id)
    SELECT user_id,provider,account_id,sender_id,message_id,job_id FROM academic_sync_notifications
    ORDER BY created_at ON CONFLICT DO NOTHING"""


def supported(target):
    return (target and target.get("provider") == "weixin_ilink"
            and all(target.get(k) for k in ("account_id", "sender_id", "message_id")))


def key(user_id, target):
    return (user_id, target["provider"], target["account_id"], target["sender_id"], target["message_id"])


def find(db, user_id, target):
    return db.execute("""SELECT j.* FROM academic_sync_requests r
        JOIN academic_sync_jobs j ON j.id=r.job_id AND j.user_id=r.user_id
        WHERE r.user_id=%s AND r.provider=%s AND r.account_id=%s AND r.sender_id=%s AND r.message_id=%s""",
        key(user_id, target)).fetchone()


def remember(db, user_id, target, job_id):
    # enqueue holds the user's transaction lock and checks find before writing.
    db.execute("""INSERT INTO academic_sync_requests(user_id,provider,account_id,sender_id,message_id,job_id)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (*key(user_id, target), job_id))
