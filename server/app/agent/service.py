"""Channel-independent entry point for a bound user's schedule agent."""
import hashlib
import re
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import db_ctx
from ..services.binding import BindingError, consume_binding_code, unbind_provider_identity
from . import clarification
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
    scope = (user_id, provider, sender_id, account_id)
    thread_key = (sender_id[:40] + "-" + hashlib.sha256(account_id.encode()).hexdigest()
                  if account_id else sender_id)
    selection_ack = None
    selection = re.fullmatch(r"使用课表\s*(\d+)", text)
    schedule_id = int(selection.group(1)) if selection else selected_schedule(user_id, provider, thread_key)
    if schedule_id is not None:
        with db_ctx(db) as conn:
            chosen = conn.execute("SELECT id,name FROM schedules WHERE id=%s AND user_id=%s",
                                  (schedule_id, user_id)).fetchone()
        if not chosen:
            if selection:
                return "没有找到这张课表，请确认课表编号。"
            schedule_id = None
        elif selection:
            if not select_schedule(user_id, provider, thread_key, schedule_id):
                return "暂时无法保存课表选择，请稍后再试。"
            selection_ack = f"已选择“{chosen['name']}”，本渠道后续查询将优先使用它，选择保留 24 小时。"
    target = ({"provider": provider, "sender_id": sender_id, "account_id": account_id,
               "message_id": message_id} if provider == "weixin_ilink" and account_id and message_id else None)
    tools = ScheduleTools(db, AgentContext(user_id, now, str(timezone), schedule_id, target))
    try:
        snapshot = tools.schedule_version()
        version = f"{snapshot}:{schedule_id or ''}"
        history = load_history(user_id, provider, thread_key, version)
    except Exception:
        # Never reuse unverifiable course facts when the snapshot cannot be read.
        import logging
        logging.getLogger(__name__).warning("Agent history snapshot unavailable", exc_info=True)
        snapshot, version, history = None, None, []
    pending = clarification.load(scope, snapshot, now)
    original_text = text
    person_choice = None
    if pending and text in {"取消", "算了", "不用了", "不查了", "取消查询", "取消追问"}:
        clarification.clear(scope)
        return "已取消刚才的待确认问题。你可以直接问新的问题。"
    if selection_ack and not pending:
        return selection_ack
    if pending and pending.people:
        person_choice = clarification.selected_person(pending, text)
    if pending and not selection and not person_choice and clarification.is_new_request(text, now.date()):
        clarification.clear(scope)
        pending = None
        history = []
    if pending:
        if pending.people:
            if person_choice is None:
                return "请按刚才的候选回复第几位、班级或学号，也可以回复“取消”。"
        elif pending.schedules:
            choice = clarification.selected_choice(pending, text)
            if choice is None:
                return "请按刚才的候选回复“第几个”，或发送“使用课表 编号”。也可以回复“取消”。"
            with db_ctx(db) as conn:
                chosen = conn.execute("SELECT id,name FROM schedules WHERE id=%s AND user_id=%s",
                                      (choice.id, user_id)).fetchone()
            if not chosen:
                clarification.clear(scope)
                return "这张课表已不可用，请重新发送查询。"
            if not select_schedule(user_id, provider, thread_key, choice.id):
                return "暂时无法保存课表选择，请稍后再试。"
            tools.context = replace(tools.context, default_schedule_id=choice.id)
            version = f"{snapshot}:{choice.id}"
            text = pending.original
        else:
            text = pending.original if selection else clarification.resume_text(pending, text)
        history = pending.history()
    if person_choice:
        import json

        from .completion import finalize
        args = {**pending.person_request, "student_id": person_choice.student_id}
        item = tools.add_other_schedule(**args)
        result = finalize({"intent": "AGENT_LOOP", "answer": item.get("message", ""), "tool_result": {
            "skills": [{"skill": "add_other_schedule", "arguments": json.dumps(args), "result": item}]}})
    else:
        result = handle_message(text, tools, history=history)
    if result.get("status") == "needs_input" and snapshot is not None:
        turns = (pending.turns + [(pending.question, original_text)]) if pending else []
        if len(turns) > 3:
            clarification.clear(scope)
            result["answer"] = "还没能确认你的意思，请把日期、课程或课表选择与原问题一起重新发送。"
        else:
            people, person_request = clarification.person_choices(result)
            waiting = clarification.PendingQuestion(
                original=pending.original if pending else original_text,
                question=result["answer"][:4000], version=snapshot,
                created_at=pending.created_at if pending else now, turns=turns,
                schedules=clarification.schedule_choices(result), people=people, person_request=person_request)
            if not clarification.save(scope, waiting):
                result["answer"] += "\n暂时无法保存这次追问，请将补充信息与原问题一起发送。"
    else:
        clarification.clear(scope)
        if result.get("status") == "needs_input":
            result["answer"] += "\n暂时无法保存这次追问，请将补充信息与原问题一起发送。"
    append_turn(row["user_id"], provider, thread_key, original_text, result["answer"], now,
                {**(result.get("resolved_context") or {"intent": result.get("intent")}),
                 "awaiting_input": result.get("status") == "needs_input"}, version)
    return result["answer"]

