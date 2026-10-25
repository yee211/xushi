"""Channel-independent entry point for a bound user's schedule agent."""
import hashlib
import re
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import db_ctx
from ..rate_limit import agent_daily_limiter
from ..services.binding import BindingError, consume_binding_code, unbind_provider_identity
from . import clarification
from .conversation import append_turn, load_history, select_schedule, selected_schedule
from .orchestrator import handle_message
from .tools import AgentContext, ScheduleTools

BINDING_RE = re.compile(r"^\s*绑定\s*([A-Za-z0-9]{6})\s*$")
# 无日期、无主语的追问碎片：既没有澄清上下文也没有可用历史时，友好提示过期。
DANGLING_FOLLOWUP = re.compile(r"^(?:那(?:么)?呢|然后呢|后来呢|结果呢|上午呢|下午呢|晚上呢|呢)[。！？?！]*$")
GUIDANCE = ("我是序时课表助手，可以查询你的课程。请先在序时小程序「AI 助手」页生成绑定码，"
            "然后给我发送：绑定 XXXXXX\n试试问我：“今天下午有什么课”、“这周有什么课”、"
            "“下一节课是什么”、“高数什么时候上”。")


def build_agent_reply(db, content: str, provider: str, sender_id: str,
                      received_at: datetime | None = None, timezone_name: str = "Asia/Shanghai",
                      account_id: str = "", message_id: str = "") -> str:
    """Bind/unbind or dispatch a text message to the shared schedule agent."""
    raw_text = str(content or "").strip()
    text = raw_text[:500]
    if len(raw_text) > len(text):
        # 让模型与对话历史都看得到截断事实，避免用户以为后半段被忽略。
        text += "（消息过长，已截断）"
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
    clear_choice = bool(pending and pending.clear_student_ids and not pending.people and
                        not pending.courses and not pending.schedules and
                        text.strip(" 。！!？?") in {"确认", "确定", "确认清空", "确定清空", "确认删除", "确定删除"})
    if pending and text in {"取消", "算了", "不用了", "不查了", "取消查询", "取消追问"}:
        clarification.clear(scope)
        return "已取消刚才的待确认问题。你可以直接问新的问题。"
    if selection_ack and not pending:
        return selection_ack
    if pending and pending.people:
        person_choice = clarification.selected_person(pending, text)
        if person_choice is None and re.fullmatch(r"\d{6,20}", text.strip()):
            # 候选未含此人（>8 截断）时，完整学号可在全名录内唯一定位
            from ..services.academic_directory import by_number_pattern
            person = by_number_pattern(text.strip())
            if person:
                person_choice = clarification.PersonChoice(
                    student_id=person["id"], name=person.get("name", ""),
                    class_name=person.get("class_name", ""),
                    student_number_display=person.get("student_number_display", ""))
    if pending and not selection and not person_choice and not clear_choice and clarification.is_new_request(text, now.date()):
        clarification.clear(scope)
        pending = None
        history = []
    if pending:
        if pending.clear_student_ids and not (pending.people or pending.courses or pending.schedules):
            if not clear_choice:
                return "确认清空全部同学课表请回复“确认”，放弃请回复“取消”。"
        elif pending.people:
            if person_choice is None:
                action = "移除" if pending.person_request.get("action") == "remove" else "添加"
                return f"请回复序号、班级或完整学号来确认要{action}的同学，也可以回复“取消”。"
        elif pending.courses:
            choice = clarification.pick_choice(pending.courses, text)
            if choice is None:
                return "请回复第几门（如“1”“第二门”）或完整课程名，也可以回复“取消”。"
            text = clarification.substitute_course(pending.original, pending.course_query, choice.name)
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
    if pending is None and not history and DANGLING_FOLLOWUP.match(re.sub(r"\s+", "", text)):
        return "刚才的对话已经过期啦，把想问的日期或课程完整发我一次就好～"
    # 每日兜底限额在渠道级分钟限流之外，覆盖所有渠道；只对真正进入问答/查询流程的消息计数。
    allowed, _retry_after = agent_daily_limiter.hit(f"{provider}:{sender_id[:64]}")
    if not allowed:
        return "今天的问题额度用完了，先歇一歇，明天再来找我吧。"
    if person_choice or clear_choice:
        import json

        from .completion import finalize
        from .skills import build_skills, dispatch
        # 候选回放按 person_request.action 路由：默认添加，删除歧义走 remove。
        if clear_choice:
            tools.clear_student_ids = pending.clear_student_ids
            args = {"confirm": True, "expected_count": len(pending.clear_student_ids)}
            skill_name = "clear_other_schedules"
        else:
            action = pending.person_request.get("action", "add")
            args = {k: v for k, v in pending.person_request.items() if k != "action"}
            args["student_id"] = person_choice.student_id
            skill_name = "remove_other_schedule" if action == "remove" else "add_other_schedule"
        item = dispatch(build_skills(tools), skill_name, json.dumps(args))
        result = finalize({"intent": "AGENT_LOOP", "answer": item.get("message", ""), "tool_result": {
            "skills": [{"skill": skill_name, "arguments": json.dumps(args), "result": item}]}})
    else:
        result = handle_message(text, tools, history=history)
    if result.get("status") == "needs_input" and snapshot is not None:
        turns = (pending.turns + [(pending.question, original_text)]) if pending else []
        if len(turns) > 3:
            clarification.clear(scope)
            result["answer"] = "还没能确认你的意思，请把日期、课程或课表选择与原问题一起重新发送。"
        else:
            people, person_request = clarification.person_choices(result)
            courses, course_query = clarification.course_choices(result)
            clear_ids = []
            for fact in reversed((result.get("tool_result") or {}).get("skills") or []):
                if fact.get("skill") == "clear_other_schedules":
                    item = fact.get("result") or {}
                    # 只有用户实际看到清空确认消息，且没有其他候选追问时才保存清空授权。
                    if not (people or courses or clarification.schedule_choices(result)) and item.get("message") == result["answer"]:
                        clear_ids = item.get("student_ids") or []
                    break
            waiting = clarification.PendingQuestion(
                original=pending.original if pending else original_text,
                question=result["answer"][:4000], version=snapshot,
                created_at=pending.created_at if pending else now, updated_at=now, turns=turns,
                schedules=clarification.schedule_choices(result), people=people, person_request=person_request,
                clear_student_ids=clear_ids,
                courses=courses, course_query=course_query)
            if not clarification.save(scope, waiting):
                result["answer"] += "\n暂时无法保存这次追问，请将补充信息与原问题一起发送。"
    else:
        clarification.clear(scope)
        if result.get("status") == "needs_input":
            result["answer"] += "\n暂时无法保存这次追问，请将补充信息与原问题一起发送。"
    append_turn(user_id, provider, thread_key, original_text, result["answer"], now,
                {**(result.get("resolved_context") or {"intent": result.get("intent")}),
                 "awaiting_input": result.get("status") == "needs_input"}, version)
    return result["answer"]

