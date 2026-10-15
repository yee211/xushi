"""工具调用主循环：LLM 面对统一注册的技能自主决策，多轮调用后给出最终回答。

没有意图枚举、没有闲聊分支——一切由模型决定是否调技能以及如何作答。
最终回答需通过接地校验（出现的时间不得超出工具结果事实集），
LLM 不可用、轮次耗尽或校验失败时返回 None，由调用方退回确定性模板路径。
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from urllib.parse import urlsplit

import httpx

from ..services.llm_config import get_llm_config
from .budget import execution, remaining
from .circuit_breaker import llm_circuit_breaker
from .http_client import post_llm
from .intent_ai import agent_config
from .polish_ai import FORBIDDEN_TOKENS, TIME_PATTERN, _api_messages
from .skills import build_skills, dispatch, openai_tools


def _post_llm(url: str, **kwargs):
    return post_llm(url, **kwargs)


logger = logging.getLogger("agent.loop")

MAX_ROUNDS = 4
MAX_TOKENS = 300

SYSTEM_PROMPT = """你是课表小程序「序时」的课表助手，身份是一位真诚、温和、靠谱的大学同学/课表搭子。结合用户消息、对话历史与服务端当前时间回答问题。
涉及课表或天气的事实时必须调用技能获取，严禁编造；回答只能使用技能返回的数据。
- 某天有什么课、有没有课用 query_day_courses；一周安排用 query_week_courses；
- 下一节课用 get_next_course；某门课什么时候上、在哪上、谁教用 find_course，
  用户用简称或口语时先 list_course_catalog 对照出完整课程名再查；
- 天气、会不会下雨、要不要带伞用 get_weather；要结合课程给带伞建议时，同时调用
  query_day_courses 和 get_weather，按上课时段给出结论；
- 问有没有空/空档用 query_day_courses 的结果自行推导。
- 问同步进度、数据是否更新、学校绑定或没有导入课表，用 get_schedule_status；只有 sync_schedule 返回成功才可宣称已提交；排队或运行中不能说已完成。
- 多课表冲突如实列出工具返回的候选，提示用户发送“使用课表 编号”，不要替用户选择。
- 历史回答不是当前事实，涉及课表和天气的追问也必须重新查询。工具不可用与没有课是两种不同结果。
- 只回答本次问题，查询课程时不要主动补充历史同步结论。后台同步结果通知可能不在对话历史里；判断同步成功、失败、未提交或仍在排队必须重新调用 get_schedule_status，不能依据历史消息猜测。
日期一律依据服务端当前时间换算成 YYYY-MM-DD。与课表无关的闲聊不调用技能，一两句话简短自然回应。
情境判断与交流分寸（重要）：
回答前先把服务端当前时间和技能返回的上课时间做对比，结合用户处境交流：
- 面对旷课/起不来/想偷懒/求劝：
  态度要真诚中肯、有分寸感。不要像教导主任训话，不要机械复读免责官话（“你自己决定我不劝也不拦”），也不要油腔滑调、强行讲烂梗；
  体谅犯困或疲惫，结合已查到的上课时间给出实在建议；不得猜测考勤要求、平时分、教师习惯；
- 面对闲聊与倾诉（“你劝劝我”、“你好冷漠”）：
  真诚体贴回应，温和解释，给予适当的情绪关怀，不生硬抗辩，不油腻嬉笑；
- 上课进行中用户说还在宿舍/床上：
  平静温和地提醒这节课已经开始（已进行约 X 分钟、还剩约 Y 分钟），提醒他赶紧收拾出发；
- 距离上课不到 15 分钟：温和提示一句“还有 N 分钟上课，别着急但也别迟到啦”；
- 相对时间按当前时间推断。
表达要求：
- 查课表时干练清晰，先给直接结论（时间、教室、教师），再按需补充细节，严禁把原始 JSON 贴出来；
- 查询一天或多天的课程列表时，固定使用“日期标题 + 项目符号课程列表 + 可选的一句自然提醒”。即使只有一节课，也必须使用项目符号“• ”，不能改成课程名开头的段落。每项严格按“开始时间–结束时间 课程名，教师，教室”排列，时间放在最前面；同一天按开始时间排序，跨日按日期分组。缺失教师或教室时省略，不编造。历史回答格式与此要求不一致时，以此要求为准。
- 单课格式示例（仅示意排版，日期、课程、教师、教室必须使用本轮工具事实，不得照抄示例）：
  明天（10月15日，周四）有1节课：
  • 08:20–10:00 开源软件开发，张宸，7-南508
  空一行后，可按真实课程情境补一句自然提醒；多课也采用同样格式逐项列出。只问教师或教室等单个细节时，直接回答该细节即可。
- 教师、教室、课程名照抄技能返回值，姓名后不要加“老师”等多余称谓；
- 语气自然平实、温和亲切，像正常微信好友交流。不要客服式套话（“好的”“亲”），不油腔滑调；
- 表情符号（Emoji）要求（严禁使用“😂”笑哭表情，按情绪与场景动态变换，每次最多 1 个，非必要不强行加）：
  - 早八 / 赖床 / 犯困：🥱、🛌、☕、💤、⏰
  - 调侃 / 看戏 / 震惊：👀、🌚、🤔、🤐、🫡
  - 催赶课 / 打气 / 劝学：🏃、🎒、💨、📚、🔥
  - 头大 / 崩溃 / 纠结：🤯、🫠、🤦、🥶
  - 下课 / 轻松 / 庆祝：🎉、🥤、✨、😎
- 严禁在回复末尾输出 [消息时间...] 或已解析上下文等系统内部标记；
- 普通回答尽量不超过 150 字；周课表或多课列表按天逐项列出，允许更长，不能因字数限制省略关键课程。
技能返回 error 时如实说明，不要猜测或虚构数据。"""


def _timeout() -> float:
    return max(3.0, min(float(os.getenv("AGENT_TIMEOUT_SECONDS", "15")), 30.0))


def _grounded(content: str, context: str) -> bool:
    """宽松接地校验：拦住编造时间、超长与元信息泄漏。

    合法时间来自工具事实及服务端当前时刻，不包含时区偏移或历史消息时间戳，
    因此模型基于事实做的时间推算（如“还剩 76 分钟”“现在 08:44”）不会被误杀。
    """
    text = str(content or "").strip()
    if not text or len(text) > 4000:
        return False
    if any(token in text.lower() for token in FORBIDDEN_TOKENS):
        return False
    def times(value):
        return {f"{int(hour):02d}:{minute}" for token in TIME_PATTERN.findall(value)
                for hour, minute in [token.split(":")]}
    allowed_times = times(str(context or ""))
    return times(text) <= allowed_times



def _facts_grounded(content: str, facts: list[dict], question: str) -> bool:
    successful = [f for f in facts if isinstance(f.get("result"), dict) and not f["result"].get("error")]
    sync_states = [(f["result"].get("sync_job") or {}).get("state")
                   for f in successful if f["skill"] == "get_schedule_status"]
    sync_states += [f["result"].get("state") for f in successful
                    if f["skill"] == "sync_schedule" and f["result"].get("ok")]
    # A failed job was submitted successfully; it cannot prove submission failed.
    not_submitted = re.search(
        r"同步.{0,12}(?:没有|未|没).{0,8}(?:提交|发起)|(?:没有|未|没).{0,8}(?:提交|发起).{0,8}同步", content)
    failure_claim = re.search(r"同步.{0,12}(?:失败|不成功|没成功|未成功|没有成功)|(?:没有|未|没|未能)同步成功", content)
    pending_claim = re.search(r"同步.{0,12}(?:尚未完成|还没完成|未完成|没有完成|排队中)|(?:正在|尚未|还未|没有|未|没)同步(?:完成)?", content)
    if not_submitted:
        return False  # Submission errors are rendered deterministically by sync.reply.
    if failure_claim:
        if "failed" not in sync_states:
            return False
    elif pending_claim and not any(state in {"queued", "running"} for state in sync_states):
        return False
    sync_assertion = re.sub(
        r"(?:尚未|还未|没有|未能|并未|未|没|等待|等|待|如果|若|直到)同步(?:已)?(?:成功|完成|好了)|同步(?:成功|完成)(?:后|时)",
        "", content)
    sync_claim = re.search(r"已(?:经)?(?:帮你|为你)?(?:提交|发起|启动).{0,8}同步|同步(?:已)?(?:成功|完成|好了)|课表已(?:经)?(?:更新|同步)", sync_assertion)
    if sync_claim:
        states = []
        for fact in successful:
            if fact["skill"] == "get_schedule_status":
                states.append((fact["result"].get("sync_job") or {}).get("state"))
            elif fact["skill"] == "sync_schedule" and fact["result"].get("ok"):
                states.append(fact["result"].get("state"))
        completed = bool(re.search(r"同步(?:已)?(?:成功|完成|好了)|课表已(?:经)?(?:更新|同步)", sync_assertion))
        if not any(state == "succeeded" if completed else state in {"queued", "running", "succeeded"}
                   for state in states):
            return False
    course_tools = {"query_day_courses", "query_week_courses", "get_next_course", "find_course"}
    queried = [f for f in successful if f["skill"] in course_tools]
    status_question = bool(re.search(r"同步|学校绑定|课表.*更新|旧课表", question))
    course_question = not status_question and bool(re.search(
        r"有什么课|有课吗|有没有.*课|课表|下一节|下节课|什么时候上|谁教|在哪上", question))
    unavailable_reply = bool(facts and not queried and re.search(
        r"查不到|无法|失败|不可用|多张|选择|范围|没有导入", content))
    if status_question and not any(f["skill"] == "get_schedule_status" for f in successful) and not unavailable_reply:
        return False
    claim = bool(re.search(r"有.{0,16}课(?!表)|没有课|正在上|下一节是|不用上课|没课|在[A-Z][A-Za-z]*-?\d{2,5}", content))
    if (course_question or claim) and not queried:
        positive = re.sub(r"没有[^，。！？\n]*|没课|不用上课", "", content)
        unsupported = bool(re.search(r"有.{0,16}课(?!表)|正在上|下一节是|在[A-Z][A-Za-z]*-?\d{2,5}|《", positive))
        if unavailable_reply:
            if unsupported:
                return False
        elif course_question or not re.search(r"可以|帮你|帮忙|能查", content):
            return False
    if queried:
        rows = []
        for fact in queried:
            result = fact["result"]
            rows.extend(result.get("courses") or [])
            rows.extend(result.get("occurrences") or [])
            if result.get("course"):
                rows.append(result["course"])
            for day in result.get("days") or []:
                rows.extend(day.get("courses") or [])
        positive = re.sub(r"没有[^，。！？\n]*|没课|不用上课", "", content)
        if not rows and re.search(r"有.{0,16}课(?!表)|正在上|下一节是", positive):
            return False
        # A single-day result cannot be rewritten as a blanket no-class conclusion.
        day_results = [f["result"] for f in queried if f["skill"] == "query_day_courses"]
        if len(day_results) == 1 and day_results[0].get("courses") and re.search(
                r"(?:今天|明天|后天|当天)?(?:没有课|没课|全天无课|没有任何课)", content):
            return False
        allowed_rooms = {str(row.get("room") or "") for row in rows}
        for room in re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Za-z]*-?\d{2,5}(?![A-Za-z0-9])", content):
            if not any(room in allowed for allowed in allowed_rooms):
                return False
        names = {str(row.get("name") or "") for row in rows}
        for name in re.findall(r"《([^》]+)》", content):
            if name not in names:
                return False
    weather_question = bool(re.search(r"天气|下雨|带伞|温度|几度", question))
    weather_claim = bool(re.search(r"晴天|多云|阴天|有雨|无雨|不会下雨|会下雨|带伞|\d+\s*(?:℃|°C|度)", content))
    if weather_question or weather_claim:
        weather = [f["result"] for f in successful if f["skill"] == "get_weather"]
        if not weather:
            return unavailable_reply and not weather_claim
        if all(r.get("rain") is None and r.get("daily") is None for r in weather):
            return bool(re.search(r"查不到|无法|不可用|暂时|未配置", content)) and not weather_claim
        rain_values = [r["rain"]["rain"] for r in weather if isinstance(r.get("rain"), dict)]
        if rain_values and all(rain_values) and re.search(r"不用带伞|不需要带伞|不会下雨|没有雨|无雨", content):
            return False
        positive_weather = re.sub(r"没有雨|不会下雨|无雨", "", content)
        if rain_values and not any(rain_values) and re.search(r"预报有雨|会下雨|有雨", positive_weather):
            return False
        daily = [r["daily"] for r in weather if isinstance(r.get("daily"), dict)]
        conditions = {r.get("condition") for r in daily}
        for condition in re.findall(r"晴间多云|雷阵雨|多云|晴天|阴天|小雨|中雨|大雨|小雪|大雪|大雾", content):
            if {"晴天": "晴", "阴天": "阴"}.get(condition, condition) not in conditions:
                return False
        temperatures = {str(r[key]) for r in daily for key in ("temp_min", "temp_max") if key in r}
        mentioned = set(re.findall(r"(?<!\d)(-?\d+)(?:\s*°[CcＣ]|\s*℃|\s*度)", content))
        for low, high in re.findall(r"(-?\d+)\s*[-～~–至]\s*(-?\d+)\s*(?:℃|°[CcＣ]|度)", content):
            mentioned.update((low, high))
        if mentioned and not mentioned <= temperatures:
            return False
    return True


def _execute_tool_call(skills, call: dict) -> tuple[dict, dict]:
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    arguments = str(function.get("arguments") or "{}")
    result = dispatch(skills, name, arguments)
    fact = {"skill": name, "arguments": arguments, "result": result}
    tool_msg = {"role": "tool", "tool_call_id": str(call.get("id") or name),
                "content": json.dumps(result, ensure_ascii=False, default=str)}
    return fact, tool_msg


def _extract_context_entities(facts: list[dict]) -> dict:
    resolved: dict = {"intent": "AGENT_LOOP", "skills": [fact["skill"] for fact in facts]}
    for fact in facts:
        if (fact.get("result") or {}).get("error"):
            continue
        raw_args = fact.get("arguments")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args = {}
        if isinstance(args, dict):
            if "date" in args and "target_date" not in resolved and args["date"]:
                resolved["target_date"] = str(args["date"])
            if "period" in args and "period" not in resolved and args["period"] != "all":
                resolved["period"] = str(args["period"])
            if "name" in args and "course_name" not in resolved and args["name"]:
                resolved["course_name"] = str(args["name"])
    return resolved


def run(tools, message: str, history: list | None = None) -> dict | None:
    try:
        with execution():
            engine = os.getenv("AGENT_ENGINE", "legacy").strip().lower()
            if engine == "legacy":
                return _run(tools, message, history)
            if engine == "langgraph":
                from .graph import run as run_graph
                return run_graph(tools, message, history)
            raise ValueError("Unsupported AGENT_ENGINE")
    except Exception as error:
        logger.warning("Agent failed: %s", type(error).__name__)
        llm_circuit_breaker.record_failure(error)
        return None
    finally:
        from .circuit_breaker import CircuitState
        if llm_circuit_breaker.state == CircuitState.HALF_OPEN:
            llm_circuit_breaker.record_failure("probe exited without a result")


def _run(tools, message: str, history: list | None = None) -> dict | None:
    base_url, api_key, model = agent_config()
    if not (base_url and api_key and model):
        return None
    config = get_llm_config("agent")
    skills = build_skills(tools)
    messages = _api_messages(SYSTEM_PROMPT, history,
                             json.dumps({"服务端当前时间": tools.context.now.isoformat(),
                                         "时区": tools.context.timezone, "用户消息": message},
                                        ensure_ascii=False))
    facts: list[dict] = []
    from .course_reply import CourseComment, course_facts, render_courses

    def saved_answer(closing=""):
        bundle = course_facts(facts, message)
        if bundle is None:
            return None
        return {"answer": render_courses(bundle, tools.context.now.date(), closing),
                "skills": [fact["skill"] for fact in facts], "tool_result": {"skills": facts},
                "resolved_context": _extract_context_entities(facts)}

    try:
        for _ in range(MAX_ROUNDS):
            remaining()
            payload = {"model": model, "temperature": 0.2, "max_tokens": int(config.get("max_tokens") or MAX_TOKENS),
                       "messages": messages, "tools": openai_tools(skills), "tool_choice": "auto"}
            structured_day = course_facts(facts, message)
            if structured_day is not None:
                payload["messages"] = messages + [{"role": "system", "content":
                    '课程列表由服务端使用工具事实生成。只输出 JSON 对象 {"closing":"一句可选的自然提醒"}。'
                    '不要输出日期、课程列表或同步状态；没有适合的提醒就返回 {"closing":""}。'}]
                payload["response_format"] = {"type": "json_object"}
                payload["tool_choice"] = "none"
            if urlsplit(base_url).hostname == "api.deepseek.com":
                # DeepSeek uses thinking.type, not the Qwen enable_thinking field.
                # Disabling it avoids multi-turn reasoning_content protocol requirements.
                payload["thinking"] = {"type": "enabled" if config.get("enable_thinking") else "disabled"}
            else:
                payload["enable_thinking"] = bool(config.get("enable_thinking", False))
            response = _post_llm(f"{base_url}/chat/completions",
                                 headers={"Authorization": f"Bearer {api_key}"}, timeout=float(config.get("timeout_seconds") or _timeout()),
                                 json=payload)
            response.raise_for_status()
            remaining()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                return saved_answer()  # Keep validated facts even when model output is truncated.
            reply = choice["message"]
            calls = reply.get("tool_calls") or []
            if not calls:
                content = str(reply.get("content") or "").strip()
                content = re.sub(r"\s*\[消息时间[:：].*?\]\s*$", "", content, flags=re.DOTALL).strip()
                content = content.replace("😂", "").strip()
                if structured_day is not None:
                    try:
                        comment = CourseComment.model_validate_json(content).closing
                    except ValueError:
                        comment = ""
                    candidate = render_courses(structured_day, tools.context.now.date(), comment)
                    if comment and not (_grounded(candidate, json.dumps([f["result"] for f in facts], ensure_ascii=False, default=str))
                                        and _facts_grounded(candidate, facts, message)):
                        candidate = render_courses(structured_day, tools.context.now.date())
                    llm_circuit_breaker.record_success()
                    return {"answer": candidate, "skills": [fact["skill"] for fact in facts],
                            "tool_result": {"skills": facts}, "resolved_context": _extract_context_entities(facts)}
                if content and _grounded(content, json.dumps([f["result"] for f in facts if not f["result"].get("error")],
                                                      ensure_ascii=False, default=str) + " " + tools.context.now.strftime("%H:%M")) and _facts_grounded(content, facts, message):
                    llm_circuit_breaker.record_success()
                    return {"answer": content, "skills": [fact["skill"] for fact in facts],
                            "tool_result": {"skills": facts},
                            "resolved_context": _extract_context_entities(facts)}
                logger.warning("Agent response rejected: %s", "empty" if not content else "grounding_validation")
                llm_circuit_breaker.record_failure("empty or ungrounded LLM response")
                return None
            assistant = {"role": "assistant", "content": str(reply.get("content") or ""), "tool_calls": calls}
            if reply.get("reasoning_content") is not None:
                assistant["reasoning_content"] = reply["reasoning_content"]
            messages.append(assistant)
            if len(calls) == 1:
                fact, tool_msg = _execute_tool_call(skills, calls[0])
                facts.append(fact)
                messages.append(tool_msg)
            else:
                with ThreadPoolExecutor(max_workers=min(len(calls), 6)) as executor:
                    futures = [executor.submit(copy_context().run, _execute_tool_call, skills, call) for call in calls]
                    results = [future.result() for future in futures]
                for fact, tool_msg in results:
                    facts.append(fact)
                    messages.append(tool_msg)
        logger.warning("Agent failed: maximum_rounds")
        llm_circuit_breaker.record_failure("agent loop exhausted maximum rounds")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        logger.warning("Agent request failed: type=%s status=%s", type(error).__name__, status)
        llm_circuit_breaker.record_failure(error)
        return saved_answer()
    return saved_answer()
