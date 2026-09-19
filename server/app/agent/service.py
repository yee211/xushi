"""Channel-independent entry point for a bound user's schedule agent."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..services.binding import BindingError, consume_binding_code, unbind_provider_identity
from .conversation import append_turn, load_history
from .orchestrator import handle_message
from .tools import AgentContext, ScheduleTools

BINDING_RE = re.compile(r"^\s*绑定\s*([A-Za-z0-9]{6})\s*$")
GUIDANCE = ("我是序时课表助手，可以查询你的课程。请先在序时小程序「AI 助手」页生成绑定码，"
            "然后给我发送：绑定 XXXXXX\n试试问我：“今天下午有什么课”、“这周有什么课”、"
            "“下一节课是什么”、“高数什么时候上”。")


def build_agent_reply(db, content: str, provider: str, sender_id: str,
                      received_at: datetime | None = None, timezone_name: str = "Asia/Shanghai",
                      account_id: str = "") -> str:
    """Bind/unbind or dispatch a text message to the shared schedule agent."""
    text = str(content or "").strip()[:500]
    if text in {"解绑", "解除绑定"}:
        if unbind_provider_identity(db, provider, sender_id):
            return "已解绑，我将无法再查询你的课表。如需继续使用，请重新发送绑定码。"
        return "你还没有绑定过，发送“绑定 XXXXXX”即可绑定。"

    match = BINDING_RE.match(text)
    if match:
        try:
            consume_binding_code(db, match.group(1), provider, sender_id, account_id)
            return "绑定成功！现在可以直接问我课表，例如“今天下午有什么课”。"
        except BindingError as error:
            return str(error)

    row = db.execute("SELECT user_id FROM user_identities WHERE provider=%s AND provider_user_id=%s",
                     (provider, sender_id)).fetchone()
    if not row:
        return GUIDANCE

    timezone = ZoneInfo(timezone_name)
    now = received_at or datetime.now(timezone)
    tools = ScheduleTools(db, AgentContext(row["user_id"], now, str(timezone)))
    history = load_history(row["user_id"], provider, sender_id)
    result = handle_message(text, tools, history=history)
    append_turn(row["user_id"], provider, sender_id, text, result["answer"], now,
                result.get("resolved_context") or {"intent": result.get("intent")})
    return result["answer"]
