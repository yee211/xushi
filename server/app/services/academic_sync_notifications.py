"""Durable completion notifications for explicitly requested ClawBot sync jobs."""
import json
import logging
import uuid

from fastapi import HTTPException

from ..channels.weixin.client import ILinkClient, ILinkError
from ..channels.weixin.protocol import Credentials
from ..channels.weixin.store import decrypt_token
from ..db import connect
from . import academic, academic_runtime

logger = logging.getLogger(__name__)
SCHEMA = (
    "ALTER TABLE academic_sync_jobs ADD COLUMN IF NOT EXISTS error_code TEXT",
    """CREATE TABLE IF NOT EXISTS academic_sync_notifications (
        id UUID PRIMARY KEY,job_id UUID NOT NULL REFERENCES academic_sync_jobs(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider TEXT NOT NULL CHECK(provider='weixin_ilink'),sender_id TEXT NOT NULL,
        account_id TEXT NOT NULL,message_id TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sending','sent','failed','cancelled')),
        attempts INTEGER NOT NULL DEFAULT 0,lease_id UUID,lease_until TIMESTAMPTZ,
        available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,sent_at TIMESTAMPTZ,error_code TEXT,
        UNIQUE(job_id,provider,sender_id,account_id))""",
    "CREATE INDEX IF NOT EXISTS idx_academic_notifications_pending ON academic_sync_notifications(state,available_at)",
)
FOLLOWUP_SCHEMA = (
    "ALTER TABLE academic_sync_notifications ADD COLUMN IF NOT EXISTS followup JSONB",
    "ALTER TABLE academic_sync_notifications ADD COLUMN IF NOT EXISTS delivery_text TEXT",
)
SCHEMA += FOLLOWUP_SCHEMA



def classify_error(error) -> str:
    if isinstance(error, academic.AcademicError):
        return error.code
    if isinstance(error, academic_runtime.SyncTimeout):
        return "sync_timeout"
    if isinstance(error, HTTPException):
        detail = str(error.detail)
        if "绑定已变更" in detail:
            return "binding_changed"
        if "绑定学校" in detail:
            return "school_not_bound"
        if "学校连接暂不可用" in detail or "学校返回的课表不完整" in detail:
            return "snapshot_incomplete"
        return "sync_rejected"
    return "internal_error"


FAILURES = {
    "connection_expired": "学校教务登录已失效或无查询权限，需要管理员重新连接教务系统后再试。",
    "connection_not_configured": "管理员尚未配置可用的教务连接，请联系管理员处理。",
    "connection_unreadable": "教务连接配置无法读取，请联系管理员修复连接。",
    "upstream_timeout": "学校教务查询超时，自动重试后仍未成功，请稍后再试。",
    "sync_timeout": "同步执行超时，自动重试后仍未成功，请稍后再试。",
    "upstream_failed": "学校教务服务暂时无法响应，请稍后再试。",
    "query_busy": "学校课表查询繁忙，自动重试后仍未成功，请稍后再试。",
    "rate_limit_unavailable": "查询限流服务暂不可用，请稍后再试。",
    "upstream_denied": "学校未允许本次查询，或该学期课表尚未发布，请在小程序检查学期。",
    "term_unavailable": "所选学期课表尚未发布，请在小程序检查学期。",
    "student_not_selected": "学校身份已不可用，请在小程序重新选择并绑定学校身份。",
    "school_not_bound": "学校身份已解绑，请在小程序重新绑定。",
    "binding_changed": "同步期间学校绑定发生变化，请重新发起同步。",
    "snapshot_incomplete": "未能取得完整的学校课表，请检查教务连接后重试。",
    "worker_interrupted": "同步多次被中断，请重新发起同步。",
}
INVALID_DATA = {"schedule_incomplete", "schedule_invalid", "schedule_mismatch", "upstream_invalid", "calendar_invalid",
                "terms_invalid", "report_invalid", "upstream_url_invalid", "upstream_too_large"}


def completion_text(job: dict) -> str:
    if job["state"] == "succeeded":
        result = job.get("result") or {}
        text = "课表同步成功，已核验学校课表，内容没有变化。" if result.get("unchanged") else "课表同步成功，已更新为学校最新课表。"
        if result.get("warnings"):
            text += "本次同步有提示，请在小程序查看详情。"
        return text
    if job["state"] != "failed":
        raise ValueError("only terminal jobs can be notified")
    code = job.get("error_code")
    reason = FAILURES.get(code)
    if code in INVALID_DATA:
        reason = "学校返回的课表数据异常或不完整，请联系管理员检查。"
    return "课表同步失败：" + (reason or "同步服务发生异常，请稍后重试；持续失败请联系管理员。") + "当前仍使用已保存的课表。"


def subscribe(db, job: dict, target: dict | None) -> bool:
    """Called inside enqueue's transaction, so subscriptions cannot be lost on commit."""
    if (not target or target.get("provider") != "weixin_ilink"
            or not all(target.get(key) for key in ("sender_id", "account_id", "message_id"))
            or job["state"] not in {"queued", "running"}):
        return False
    if target.get("followup"):
        from ..agent.sync_followup import FollowupPlan
        plan = FollowupPlan.model_validate(target["followup"]).model_dump(mode="json")
        # Do not replace another message's continuation on a reused active job.
        # A replay of the exact original message reuses its immutable plan.
        row = db.execute("""INSERT INTO academic_sync_notifications
            (id,job_id,user_id,provider,sender_id,account_id,message_id,followup)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(job_id,provider,sender_id,account_id) DO NOTHING RETURNING id""",
            (uuid.uuid4(), job["id"], job["user_id"], target["provider"], target["sender_id"],
             target["account_id"], target["message_id"], json.dumps(plan, ensure_ascii=False))).fetchone()
        if row:
            return True
        existing = db.execute("""SELECT followup FROM academic_sync_notifications
            WHERE job_id=%s AND user_id=%s AND provider=%s AND sender_id=%s AND account_id=%s
            AND message_id=%s AND state IN ('pending','sending')""",
            (job["id"], job["user_id"], target["provider"], target["sender_id"],
             target["account_id"], target["message_id"])).fetchone()
        return bool(existing and existing.get("followup") == plan)
    row = db.execute("""INSERT INTO academic_sync_notifications(id,job_id,user_id,provider,sender_id,account_id,message_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(job_id,provider,sender_id,account_id) DO UPDATE SET message_id=EXCLUDED.message_id
        WHERE academic_sync_notifications.state='pending' AND academic_sync_notifications.followup IS NULL AND NOT EXISTS (
            SELECT 1 FROM channel_messages m WHERE m.provider=academic_sync_notifications.provider
            AND m.account_id=academic_sync_notifications.account_id
            AND m.message_id=academic_sync_notifications.message_id AND m.status='done') RETURNING id""",
        (uuid.uuid4(), job["id"], job["user_id"], target["provider"], target["sender_id"],
         target["account_id"], target["message_id"])).fetchone()
    return bool(row)


def claim(db):
    # Network I/O happens after this short transaction releases the row locks.
    db.execute("""UPDATE academic_sync_notifications SET state='failed',error_code='delivery_exhausted'
        WHERE state='sending' AND lease_until<CURRENT_TIMESTAMP AND attempts>=3""")
    row = db.execute("""UPDATE academic_sync_notifications SET state='sending',attempts=attempts+1,
        lease_id=%s,lease_until=CURRENT_TIMESTAMP + INTERVAL '60 seconds'
        WHERE id=(SELECT n.id FROM academic_sync_notifications n
            JOIN academic_sync_jobs j ON j.id=n.job_id AND j.user_id=n.user_id
            WHERE j.state IN ('succeeded','failed') AND n.attempts<3
            AND (n.state='pending' OR (n.state='sending' AND n.lease_until<CURRENT_TIMESTAMP))
            AND n.available_at<=CURRENT_TIMESTAMP
            AND EXISTS (SELECT 1 FROM channel_messages m WHERE m.provider=n.provider
                AND m.account_id=n.account_id AND m.message_id=n.message_id
                AND (m.status='done' OR m.status='dead_letter'
                     OR (m.status='failed' AND m.attempts>=3)))
            ORDER BY n.created_at LIMIT 1 FOR UPDATE OF n SKIP LOCKED)
        RETURNING *""", (uuid.uuid4(),)).fetchone()
    if not row:
        return None
    job = db.execute("SELECT state,result,error_code,student_id,binding_revision,binding_updated_at FROM academic_sync_jobs WHERE id=%s AND user_id=%s",
                     (row["job_id"], row["user_id"])).fetchone()
    return row, job


def deliver(row: dict, job: dict) -> None:
    # Check the original channel identity again: never follow a recipient to another account.
    with connect() as db:
        account = db.execute("""SELECT u.context_token,c.bot_token_encrypted,c.api_base_url,c.admin_user_id
            FROM user_identities u JOIN channel_accounts c ON c.provider=u.provider AND c.account_id=u.account_id
            WHERE u.user_id=%s AND u.provider=%s AND u.provider_user_id=%s AND u.account_id=%s
            AND c.status='active'""", (row["user_id"], row["provider"], row["sender_id"], row["account_id"])).fetchone()
    if not account or not account.get("context_token"):
        finish(row, "cancelled", "recipient_unavailable")
        return
    client = None
    try:
        credentials = Credentials(row["account_id"], decrypt_token(account["bot_token_encrypted"]),
                                  account["api_base_url"], account.get("admin_user_id") or "")
        if row.get("followup"):
            from .academic_sync_followup import delivery_text
            text = delivery_text(row, job)
        else:
            text = row.get("delivery_text") or completion_text(job)
        # All deliveries must still own a live lease, including plain notices.
        with connect() as db:
            saved = db.execute("""UPDATE academic_sync_notifications SET delivery_text=%s,
                lease_until=CURRENT_TIMESTAMP + INTERVAL '60 seconds'
                WHERE id=%s AND state='sending' AND lease_id=%s AND lease_until>CURRENT_TIMESTAMP
                RETURNING id""", (text, row["id"], row["lease_id"])).fetchone()
        if not saved:
            return
        client = ILinkClient(credentials)
        client.send_text(row["sender_id"], text, account["context_token"],
                         client_id=f"sync_{row['id']}")
    except ILinkError as error:
        terminal = str(error.code) in {"-2", "-14"}
        finish(row, "failed" if terminal or row["attempts"] >= 3 else "pending",
               "channel_expired" if terminal else "delivery_failed")
        logger.warning("Sync notification rejected id=%s code=%s", row["id"], error.code)
    except Exception:
        # Avoid recording credentials, context tokens or upstream error bodies.
        finish(row, "failed" if row["attempts"] >= 3 else "pending", "delivery_failed")
        logger.warning("Sync notification unavailable id=%s", row["id"])
    else:
        finish(row, "sent")
    finally:
        if client is not None:
            client.close()


def finish(row, state, error_code=None):
    with connect() as db:
        db.execute("""UPDATE academic_sync_notifications SET state=%s,error_code=%s,
            sent_at=CASE WHEN %s='sent' THEN CURRENT_TIMESTAMP ELSE sent_at END,
            available_at=CURRENT_TIMESTAMP + INTERVAL '30 seconds',lease_until=NULL
            WHERE id=%s AND state='sending' AND lease_id=%s""",
            (state, error_code, state, row["id"], row["lease_id"]))


def dispatch_one() -> bool:
    with connect() as db:
        item = claim(db)
    if item is None:
        return False
    deliver(*item)
    return True
