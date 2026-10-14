"""Channel-independent entry point for a bound user's schedule agent."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import db_ctx
from ..services.binding import BindingError, consume_binding_code, unbind_provider_identity
from .conversation import append_turn, load_history, select_schedule, selected_schedule
from .orchestrator import handle_message
from .tools import AgentContext, ScheduleTools

BINDING_RE = re.compile(r"^\s*绑定\s*([A-Za-z0-9]{6})\s*$")
GUIDANCE = ("我是序时课表助手，可以查询你的课程。请先在序时小程序「AI 助手」页生成绑定码，"
            "然后给我发送：绑定 XXXXXX\n试试问我：“今天下午有什么课”、“这周有什么课”、"
            "“下一节课是什么”、“高数什么时候上”。")


def build_agent_reply(db, content: str, provider: str, sender_id: str,
                      received_at: datetime | None = None, timezone_name: str = "Asia/Shanghai",
                      account_id: str = "", message_id: str = "") -> str:
    """Bind/unbind or dispatch a text message to the shared schedule agent."""
    text = str(content or "").strip()[:500]
    if text in {"解绑", "解除绑定"}:
        with db_ctx(db) as conn:
            if unbind_provider_identity(conn, provider, sender_id):
                return "已解绑，我将无法再查询你的课表。如需继续使用，请重新发送绑定码。"
            return "你还没有绑定过，发送“绑定 XXXXXX”即可绑定。"

    match = BINDING_RE.match(text)
    if match:
        with db_ctx(db) as conn:
            try:
                consume_binding_code(conn, match.group(1), provider, sender_id, account_id)
                return "绑定成功！现在可以直接问我课表，例如“今天下午有什么课”。"
            except BindingError as error:
                return str(error)

    with db_ctx(db) as conn:
        row = conn.execute("SELECT user_id FROM user_identities WHERE provider=%s AND provider_user_id=%s",
                           (provider, sender_id)).fetchone()
    if not row:
        return GUIDANCE

    timezone = ZoneInfo(timezone_name)
    now = received_at or datetime.now(timezone)
    # ScheduleTools 内部按需借还连接；在 handle_message 等待大模型网络响应时，零数据库连接占用
    user_id = row["user_id"]
    selection = re.fullmatch(r"使用课表\s*(\d+)", text)
    schedule_id = int(selection.group(1)) if selection else selected_schedule(user_id, provider, sender_id)
    if schedule_id is not None:
        with db_ctx(db) as conn:
            chosen = conn.execute("SELECT id,name FROM schedules WHERE id=%s AND user_id=%s",
                                  (schedule_id, user_id)).fetchone()
        if not chosen:
            if selection:
                return "没有找到这张课表，请确认课表编号。"
            schedule_id = None
        elif selection:
            if not select_schedule(user_id, provider, sender_id, schedule_id):
                return "暂时无法保存课表选择，请稍后再试。"
            return f"已选择“{chosen['name']}”，本渠道后续查询将优先使用它，选择保留 24 小时。"
    target = ({"provider": provider, "sender_id": sender_id, "account_id": account_id,
               "message_id": message_id} if provider == "weixin_ilink" and account_id and message_id else None)
    tools = ScheduleTools(db, AgentContext(user_id, now, str(timezone), schedule_id, target))
    try:
        version = f"{tools.schedule_version()}:{schedule_id or ''}"
        history = load_history(user_id, provider, sender_id, version)
    except Exception:
        # Never reuse unverifiable course facts when the snapshot cannot be read.
        import logging
        logging.getLogger(__name__).warning("Agent history snapshot unavailable", exc_info=True)
        version, history = None, []
    result = handle_message(text, tools, history=history)
    append_turn(row["user_id"], provider, sender_id, text, result["answer"], now,
                result.get("resolved_context") or {"intent": result.get("intent")}, version)
    return result["answer"]

