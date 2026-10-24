"""Agent 消息入口：LLM 工具调用循环优先，确定性规则路径兜底。"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

from ..services import agent_metrics
from ..services.schedule_query import ScheduleQueryError, resolve_course_name
from ..services.weather import day_rain, fetch_daily_weather, rain_advisory
from . import telemetry
from .budget import available, execution
from .circuit_breaker import CircuitState, llm_circuit_breaker
from .intent_ai import extract_intent, llm_configured
from .loop import run as run_agent
from .polish_ai import polish_answer, small_talk
from .tools import ScheduleTools

DAYS = "一二三四五六日"
DAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PERIOD_LABELS = {"all": "", "morning": "上午", "afternoon": "下午", "evening": "晚上"}
COURSE_QUERY_MARKERS = ("什么时候", "啥时候", "哪天", "几点", "老师是谁", "哪个老师", "谁上", "谁教", "在哪", "哪里")
HAS_COURSE_PATTERN = re.compile(r"(?:有没有|没有|有)(.{1,12}?)课")
HAS_COURSE_JUNK = "有没吗么什啥多少哪几"
LEADING_FILLERS = ("请问", "帮我查一下", "帮我查下", "帮我查", "帮我看看", "查一下", "查下", "看看", "有没有", "有",
                   "这学期", "下下周", "这一周", "下周", "这周", "本周", "上周", "这星期", "下星期", "本星期",
                   "后天", "明天", "今天", "明日", "今日", "明早", "早上", "上午", "下午", "晚上", "晚间",
                   "我们", "咱们", "我", "你")
WEEK_OFFSETS = (("下下周", 2), ("这一周", 0), ("下周", 1), ("这周", 0), ("本周", 0), ("下星期", 1), ("这星期", 0), ("本星期", 0))
TRAILING_PARTICLES = "的吗呢吧了呢啊呀哟是"

@dataclass(frozen=True)
class ParsedIntent:
    name: str
    target_date: date | None = None
    period: str = "all"
    weekday: int | None = None
    course_name: str = ""

def _target_day(text: str, today: date) -> date | None:
    if "后天" in text:
        return today + timedelta(days=2)
    if "明天" in text or "明日" in text:
        return today + timedelta(days=1)
    if "今天" in text or "今日" in text:
        return today
    match = re.search(r"(?:(下下|上|下|本|这)(?:周|星期)|星期|周)([一二三四五六日天])", text)
    if not match:
        return None
    weekday = 7 if match.group(2) == "天" else DAYS.index(match.group(2)) + 1
    monday = today - timedelta(days=today.isoweekday() - 1)
    week_offset = {"下下": 2, "下": 1, "上": -1}.get(match.group(1), 0)
    return monday + timedelta(days=week_offset * 7 + weekday - 1)

def _clean_course_name(raw: str) -> str:
    changed = True
    while changed and raw:
        changed = False
        for filler in LEADING_FILLERS:
            if raw.startswith(filler):
                raw = raw[len(filler):]
                changed = True
                break
        if len(raw) > 1 and raw[-1] in TRAILING_PARTICLES + "课的":
            raw = raw[:-1]
            changed = True
    return raw

def _course_query(text: str) -> str | None:
    """Extract a course name from questions like “高数什么时候上”；无把握时返回 None 交给兜底。"""
    for marker in COURSE_QUERY_MARKERS:
        index = text.find(marker)
        if index < 0:
            continue
        for raw in (text[:index], text[index + len(marker):]):
            candidate = _clean_course_name(raw)
            if 2 <= len(candidate) <= 16 and candidate not in {"课", "课表", "课程", "什么课", "啥课"}:
                return candidate
    return None

def is_date_only(text: str) -> bool:
    return bool(re.fullmatch(
        r"(?:那|那么)?(?:今天|今日|明天|明日|后天|"
        r"(?:(?:下下|上|下|本|这)?(?:周|星期))[一二三四五六日天])"
        r"(?:早上|上午|下午|晚上|晚间)?[呢啊呀吗吧?？!！。]*", text))


def parse_intent(message: str, today: date) -> ParsedIntent:
    text = re.sub(r"\s+", "", str(message or ""))
    if not text:
        return ParsedIntent("HELP")
    if "下一节" in text or "接下来" in text or "下节课" in text:
        return ParsedIntent("QUERY_NEXT")
    period = "morning" if any(x in text for x in ("上午", "早上", "明早")) else (
        "afternoon" if "下午" in text else ("evening" if any(x in text for x in ("晚上", "晚间")) else "all"))
    target = _target_day(text, today)
    if any(x in text for x in ("有空", "空不空", "空闲", "忙不忙", "忙吗")):
        return ParsedIntent("QUERY_AVAILABILITY", target, period) if target else ParsedIntent("HELP")
    course_name = _course_query(text)
    if course_name:
        return ParsedIntent("FIND_COURSE", course_name=course_name)
    # “明天要带伞吗”“今天会下雨吗”这类天气是非问句：有明确日期即按天气意图处理。
    if target and any(word in text for word in ("天气", "雨", "带伞", "温度", "几度")):
        return ParsedIntent("QUERY_WEATHER", target, period)
    match = HAS_COURSE_PATTERN.search(text)
    if target and match:
        candidate = match.group(1)
        if 2 <= len(candidate) <= 12 and not any(character in candidate for character in HAS_COURSE_JUNK):
            return ParsedIntent("QUERY_COURSE_ON_DAY", target, period, course_name=candidate)
    # “今天”这类词也出现在闲聊里（如“今天天气怎么样”），仅当消息与课程相关时才按日期查询。
    # 日期短句常用于回答日期澄清或连续追问，例如“今天”“下周一呢”。
    # 完整匹配，避免把“下周一去吃饭”等普通聊天当成查课。
    date_only = is_date_only(text)
    if target and (date_only or any(x in text for x in ("课", "安排", "忙", "空"))):
        intent = "QUERY_AVAILABILITY" if any(
            x in text for x in ("有空", "空不空", "空闲", "忙不忙", "忙吗")) else "QUERY_DAY"
        return ParsedIntent(intent, target, period)
    if "课" in text:
        for word, offset in WEEK_OFFSETS:
            if word in text:
                monday = today - timedelta(days=today.isoweekday() - 1) + timedelta(weeks=offset)
                return ParsedIntent("QUERY_WEEK", monday)
    return ParsedIntent("HELP")

def _course_line(item: dict) -> str:
    place = f"，{item['room']}" if item.get("room") else ""
    teacher = f"，{item['teacher']}" if item.get("teacher") else ""
    adjusted = "（已调课）" if item.get("adjusted") else ""
    return (f"{item['start_time']}–{item['end_time']}（第{item['start_section']}–{item['end_section']}节）"
            f"{item['name']}{place}{teacher}{adjusted}")

def handle_message(message: str, tools: ScheduleTools, history: list | None = None) -> dict:
    """LLM 工具调用循环优先：模型自主决定调哪些技能、如何作答。

    循环不可用（LLM 未配置/熔断中/超时/输出未过接地校验）时，退回确定性意图+模板路径兜底。
    """
    telemetry.start_turn()
    started = time.perf_counter()
    try:
        with execution():
            from .completion import finalize
            result = finalize(_handle_message(message, tools, history))
            telemetry.note_tool_errors(result.get("tool_result"))
            return result
    finally:
        _log_turn(started)


def _log_turn(started: float) -> None:
    stats = telemetry.active()
    if stats is None:
        return
    turn = {
        "path": stats.path or "unknown",
        "outcome": stats.outcome or "ok",
        "rounds": stats.rounds,
        "llm_calls": stats.llm_calls,
        "prompt_tokens": stats.prompt_tokens,
        "completion_tokens": stats.completion_tokens,
        "cached_tokens": stats.cached_tokens,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "breaker": str(llm_circuit_breaker.state),
    }
    if stats.tool_errors:
        # outcome=ok 只代表 LLM 循环正常返回；工具错误码单列，运维可按码聚合告警。
        turn["tool_errors"] = stats.tool_errors
    logging.getLogger("classschedule").info(json.dumps({"event": "agent_turn", **turn}, ensure_ascii=False))
    agent_metrics.enqueue(turn)


def _handle_message(message: str, tools: ScheduleTools, history: list | None = None) -> dict:
    from .peer_sync import handle as handle_peer_sync
    from .sync import query_status, reply, requested, status_requested
    peer_result = handle_peer_sync(message, tools, history)
    if peer_result is not None:
        telemetry.note(path="sync")
        return peer_result
    if requested(message):
        telemetry.note(path="sync")
        tools.sync_authorized = True
        from .sync_followup import completed_reply, prepare
        plan = prepare(message, tools.context.now)
        if tools.context.notification_target:
            tools.sync_followup = plan
        result = tools.sync_schedule()
        response = reply(result, message)
        if result.get("ok") and result.get("state") == "succeeded" and plan:
            response["answer"] = completed_reply(result, plan, tools)
        return response
    if status_requested(message, history):
        telemetry.note(path="status")
        return query_status(tools, message)
    # llm_configured 是测试用来强制关闭 LLM 路径的开关；本轮只调用一次，供 LLM 与兜底路径共用。
    llm_ready = llm_configured()
    llm_allowed = llm_ready and llm_circuit_breaker.allow_request()
    if llm_allowed:
        looped = run_agent(tools, message, history)
        if looped:
            stats = telemetry.active()
            telemetry.note(path="llm", outcome=(stats.outcome if stats and stats.outcome else "ok"))
            return {"intent": "AGENT_LOOP", "answer": looped["answer"],
                    "_completion_status": looped.get("_completion_status"),
                    "tool_result": looped["tool_result"],
                    "resolved_context": looped.get("resolved_context") or {"intent": "AGENT_LOOP", "skills": looped["skills"]}}
        stats = telemetry.active()
        telemetry.note(path="llm",
                       outcome=(stats.outcome if stats and stats.outcome else "llm_unavailable"))
    # OPEN/HALF_OPEN fallback must remain entirely deterministic. When the breaker
    # is still CLOSED, retain the existing intent-extraction/polishing fallback.
    telemetry.note(path="fallback")
    return _fallback_reply(message, tools, history,
                           allow_llm=available() and llm_circuit_breaker.state == CircuitState.CLOSED,
                           llm_ready=llm_ready)


def _fallback_reply(message: str, tools: ScheduleTools, history: list | None = None,
                  *, allow_llm: bool = True, llm_ready: bool = True) -> dict:
    from .sync import query_status, status_requested
    if status_requested(message, history):
        return query_status(tools, message)
    # The personal-only fallback must not answer a question about another person.
    # Resolve saved names locally as well as generic references such as “室友”.
    text = re.sub(r"\s+", "", message)
    if is_date_only(text):
        for item in reversed(history or []):
            role = item.get("role") if isinstance(item, dict) else getattr(item, "type", None)
            if role in {"user", "human"}:
                content = item.get("content", "") if isinstance(item, dict) else item.content
                text += re.sub(r"\s+", "", str(content).split("[消息时间", 1)[0])
                break
    from .other_reply import group_request, mentions_others
    other_scope = mentions_others(text)
    if not other_scope:
        try:
            people = tools.list_other_people().get("people") or []
            other_scope = bool(people) and (mentions_others(text, people) or group_request(text))
        except Exception:
            return {"intent": "HELP", "answer": "暂时无法确认查询对象，请稍后重试。",
                    "error": {"code": "service_unavailable", "message": "无法读取已保存的同学课表名单"}}
    if other_scope:
        return {"intent": "HELP", "answer": "本次未能完成同学课表或多人空闲查询，请稍后重试。",
                "error": {"code": "other_query_unavailable", "message": "同学课表查询暂不可用"}}
    try:
        # 课程目录只有 LLM 意图提取会用到；纯规则路径不查，省一次数据库往返。
        catalog = tools.list_course_catalog() if allow_llm and llm_ready else []
    except ScheduleQueryError:
        catalog = []
    extracted = (extract_intent(message, tools.context.now.date(), received_at=tools.context.now.isoformat(),
                                course_catalog=catalog, history=history)
                 if allow_llm else None)
    if extracted and extracted["name"] != "HELP":
        target = date.fromisoformat(extracted["target_date"]) if extracted["target_date"] else None
        intent = ParsedIntent(extracted["name"], target, extracted["period"], extracted["weekday"],
                              extracted["course_name"])
    else:
        intent = parse_intent(message, tools.context.now.date())
    try:
        if intent.name == "QUERY_NEXT":
            result = tools.get_next_course()
            course = result.get("course")
            if not course:
                answer = "未来 7 天内没有查到课程。"
            else:
                prefix = "你正在上" if result["status"] == "ongoing" else "下一节是"
                answer = f"{prefix}：{result['date']} {_course_line(course)}。"
        elif intent.name in {"QUERY_DAY", "QUERY_AVAILABILITY"} and intent.target_date:
            result = tools.get_courses_by_date(intent.target_date, intent.period)
            courses = result["courses"]
            from .course_reply import DayCourses, list_question, render_day
            if intent.name == "QUERY_DAY" and list_question(message):
                answer = render_day(DayCourses.model_validate(dict(result, period=intent.period)), tools.context.now.date())
                advisory = rain_advisory(result["date"], courses) if courses else None
                if advisory:
                    answer += "\n\n" + advisory
                return {"intent": intent.name, "answer": answer, "tool_result": result,
                        "resolved_context": {"intent": intent.name, "target_date": result["date"], "period": intent.period}}
            day = f"{result['date']}（{DAY_LABELS[result['weekday'] - 1]}）{PERIOD_LABELS[intent.period]}"
            if intent.name == "QUERY_AVAILABILITY":
                answer = f"{day}没有课，你有空。" if not courses else f"{day}有 {len(courses)} 门课，不是整段空闲：\n" + "\n".join(
                    f"{i}. {_course_line(item)}" for i, item in enumerate(courses, 1))
            else:
                answer = f"{day}没有课。" if not courses else f"{day}有 {len(courses)} 门课：\n" + "\n".join(
                    f"{i}. {_course_line(item)}" for i, item in enumerate(courses, 1))
        elif intent.name == "QUERY_COURSE_ON_DAY" and intent.target_date and intent.course_name:
            resolved = resolve_course_name(intent.course_name, tools.list_course_catalog(intent.target_date))
            if resolved["status"] == "ambiguous":
                names = "、".join(item["name"] for item in resolved["candidates"])
                return {"intent": intent.name, "answer": f"“{intent.course_name}”可能是：{names}。你指哪一门？",
                        "tool_result": {"course_match": resolved},
                        "resolved_context": {"intent": intent.name, "course_name": intent.course_name}}
            display = resolved["course"]["name"] if resolved["course"] else intent.course_name
            result = tools.get_courses_by_date(intent.target_date, intent.period)
            courses = result["courses"]
            day = f"{result['date']}（{DAY_LABELS[result['weekday'] - 1]}）{PERIOD_LABELS[intent.period]}"
            hits = [item for item in courses if item["name"] == display] if resolved["course"] else []
            if hits:
                listing = "\n".join(f"{index}. {_course_line(item)}" for index, item in enumerate(hits, 1))
                answer = f"{day}有{display}课：\n{listing}"
            else:
                # 先给直接结论，再附当天的全部课程，避免答非所问。
                answer = f"{day}没有{display}课。"
                if courses:
                    listing = "\n".join(f"{index}. {_course_line(item)}" for index, item in enumerate(courses, 1))
                    answer += f"当天有这 {len(courses)} 门课：\n{listing}"
        elif intent.name == "QUERY_WEATHER" and intent.target_date:
            # 天气是非问句：直接回答会不会下雨，再带上当天的课程语境。
            try:
                courses = tools.get_courses_by_date(intent.target_date, "all")["courses"]
            except ScheduleQueryError:
                courses = []
            target = intent.target_date
            day = f"{target.isoformat()}（{DAY_LABELS[target.isoweekday() - 1]}）{PERIOD_LABELS[intent.period]}"
            rain = day_rain(target, intent.period)
            daily = fetch_daily_weather(target)
            if rain is None:
                answer = f"暂时查不到{day}的天气，稍后再问我吧。"
            elif rain["rain"]:
                answer = f"{day}预报有雨（降水概率最高 {rain['peak']}%），记得带伞。"
                advisory = rain_advisory(target.isoformat(), courses) if courses else None
                if advisory:
                    answer += f"\n{advisory}"
                elif courses:
                    answer += f"当天有 {len(courses)} 门课。"
            else:
                answer = f"{day}目前预报没有雨，不用带伞。"
                if courses:
                    answer += f"当天有 {len(courses)} 门课，正常出门就行。"
            if daily:
                summary = f"全天{daily['condition']}，气温 {daily['temp_min']}～{daily['temp_max']}℃。"
                answer = f"{day}{summary}" if rain is None else f"{answer}\n{summary}"
            result = {"date": target.isoformat(), "weekday": target.isoweekday(),
                      "courses": courses, "rain": rain, "daily": daily}
        elif intent.name == "QUERY_WEEK" and intent.target_date:
            result = tools.get_courses_by_week(intent.target_date, intent.weekday)
            from .course_reply import CourseList, render_courses
            answer = render_courses(CourseList.model_validate(result), tools.context.now.date())
            return {"intent": intent.name, "answer": answer, "tool_result": result,
                    "resolved_context": {"intent": intent.name, "target_date": intent.target_date.isoformat()}}
        elif intent.name == "FIND_COURSE" and intent.course_name:
            catalog = tools.list_course_catalog(intent.target_date)
            resolved = resolve_course_name(intent.course_name, catalog)
            if resolved["status"] == "matched":
                intent = ParsedIntent("FIND_COURSE", intent.target_date, intent.period,
                                      intent.weekday, resolved["course"]["name"])
            elif resolved["status"] == "ambiguous":
                names = "、".join(item["name"] for item in resolved["candidates"])
                return {"intent": intent.name, "answer": f"“{intent.course_name}”可能是：{names}。你指哪一门？",
                        "tool_result": {"course_match": resolved},
                        "resolved_context": {"intent": intent.name, "course_name": intent.course_name}}
            result = tools.find_course(intent.course_name, intent.target_date or tools.context.now.date())
            rows = result["occurrences"]
            answer = f"未来没有查到“{intent.course_name}”。" if not rows else f"“{rows[0]['name']}”接下来的上课时间：\n" + "\n".join(
                f"{index}. {item['date']} {_course_line(item)}" for index, item in enumerate(rows[:8], 1))
        else:
            result = None
            answer = "你可以问我：今天下午有什么课、明天有课吗、明天要带伞吗、这周有什么课、下周三有什么课、下一节课是什么，或者“高数什么时候上”。"
            chatted = small_talk(message, history) if allow_llm and llm_ready else None
            if chatted:
                answer = chatted
        if intent.name in {"QUERY_DAY", "QUERY_COURSE_ON_DAY"} and result and result.get("courses"):
            # 当日/次日课程列表追加降雨提醒；天气不可用时静默跳过。
            advisory = rain_advisory(result["date"], result["courses"])
            if advisory:
                answer += f"\n{advisory}"
        if result and allow_llm and available():
            # 事实来自工具结果，模板只是基准表达；润色失败或未通过接地校验时保持模板。
            polished = polish_answer(message, answer, result, history, tools.context.now)
            if polished:
                answer = polished
        resolved_context = {"intent": intent.name,
                            "target_date": intent.target_date.isoformat() if intent.target_date else None,
                            "period": intent.period, "weekday": intent.weekday,
                            "course_name": intent.course_name or None}
        return {"intent": intent.name, "answer": answer, "tool_result": result,
                "resolved_context": resolved_context}
    except ScheduleQueryError as error:
        messages = {"OUTSIDE_TERM": "这个日期不在已导入课表的学期范围内。",
                    "AMBIGUOUS_SCHEDULE": error.message}
        return {"intent": intent.name, "answer": messages.get(error.code, error.message),
                "error": {"code": error.code, "message": error.message,
                          **({"candidates": error.candidates} if error.candidates else {})}}
