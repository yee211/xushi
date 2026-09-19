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

import httpx

from .circuit_breaker import llm_circuit_breaker
from .http_client import get_llm_client, is_httpx_post_patched
from .intent_ai import agent_config
from .polish_ai import FORBIDDEN_TOKENS, TIME_PATTERN, _api_messages
from .skills import build_skills, dispatch, openai_tools


def _post_llm(url: str, **kwargs):
    if is_httpx_post_patched():
        return httpx.post(url, **kwargs)
    return get_llm_client().post(url, **kwargs)

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
日期一律依据服务端当前时间换算成 YYYY-MM-DD。与课表无关的闲聊不调用技能，一两句话简短自然回应。
情境判断与交流分寸（重要）：
回答前先把服务端当前时间和技能返回的上课时间做对比，结合用户处境交流：
- 面对旷课/起不来/想偷懒/求劝：
  态度要真诚中肯、有分寸感。不要像教导主任训话，不要机械复读免责官话（“你自己决定我不劝也不拦”），也不要油腔滑调、强行讲烂梗；
  像靠谱同门一样体谅犯困或疲惫，结合课程信息给出中肯实在的提醒或建议（例如说明天第一节课抓考勤/算平时分，实在困带杯咖啡去后排听听，别因为缺勤影响期末等）；
- 面对闲聊与倾诉（“你劝劝我”、“你好冷漠”）：
  真诚体贴回应，温和解释，给予适当的情绪关怀，不生硬抗辩，不油腻嬉笑；
- 上课进行中用户说还在宿舍/床上：
  平静温和地提醒这节课已经开始（已进行约 X 分钟、还剩约 Y 分钟），提醒他赶紧收拾出发；
- 距离上课不到 15 分钟：温和提示一句“还有 N 分钟上课，别着急但也别迟到啦”；
- 相对时间按当前时间推断。
表达要求：
- 查课表时干练清晰，先给直接结论（时间、教室、教师），再按需补充细节，严禁把原始 JSON 贴出来；
- 教师、教室、课程名照抄技能返回值，姓名后不要加“老师”等多余称谓；
- 语气自然平实、温和亲切，像正常微信好友交流。不要客服式套话（“好的”“亲”），不油腔滑调；
- 表情符号（Emoji）要求（严禁使用“😂”笑哭表情，按情绪与场景动态变换，每次最多 1 个，非必要不强行加）：
  - 早八 / 赖床 / 犯困：🥱、🛌、☕、💤、⏰
  - 调侃 / 看戏 / 震惊：👀、🌚、🤔、🤐、🫡
  - 催赶课 / 打气 / 劝学：🏃、🎒、💨、📚、🔥
  - 头大 / 崩溃 / 纠结：🤯、🫠、🤦、🥶
  - 下课 / 轻松 / 庆祝：🎉、🥤、✨、😎
- 严禁在回复末尾输出 [消息时间...] 或已解析上下文等系统内部标记；
- 保留关键事实，整体简练不超过 150 字，结尾不要补多余标点。
技能返回 error 时如实说明，不要猜测或虚构数据。"""


def _timeout() -> float:
    return max(3.0, min(float(os.getenv("AGENT_TIMEOUT_SECONDS", "15")), 30.0))


def _grounded(content: str, context: str) -> bool:
    """宽松接地校验：拦住编造时间、超长与元信息泄漏。

    合法时间来自整个对话上下文（工具结果、历史消息、服务端当前时间），
    因此模型基于事实做的时间推算（如“还剩 76 分钟”“现在 08:44”）不会被误杀。
    """
    text = str(content or "").strip()
    if not text or len(text) > 600:
        return False
    if any(token in text.lower() for token in FORBIDDEN_TOKENS):
        return False
    allowed_times = set(TIME_PATTERN.findall(str(context or "")))
    return set(TIME_PATTERN.findall(text)) <= allowed_times


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
    base_url, api_key, model = agent_config()
    if not (base_url and api_key and model):
        return None
    skills = build_skills(tools)
    messages = _api_messages(SYSTEM_PROMPT, history,
                             json.dumps({"服务端当前时间": tools.context.now.isoformat(),
                                         "时区": tools.context.timezone, "用户消息": message},
                                        ensure_ascii=False))
    facts: list[dict] = []
    try:
        for _ in range(MAX_ROUNDS):
            response = _post_llm(f"{base_url}/chat/completions",
                                 headers={"Authorization": f"Bearer {api_key}"}, timeout=_timeout(),
                                 json={"model": model, "temperature": 0.2, "max_tokens": MAX_TOKENS,
                                       "enable_thinking": False, "messages": messages,
                                       "tools": openai_tools(skills), "tool_choice": "auto"})
            response.raise_for_status()
            reply = response.json()["choices"][0]["message"]
            calls = reply.get("tool_calls") or []
            if not calls:
                content = str(reply.get("content") or "").strip()
                content = re.sub(r"\s*\[消息时间[:：].*?\]\s*$", "", content, flags=re.DOTALL).strip()
                content = content.replace("😂", "").strip()
                if content and _grounded(content, json.dumps(messages, ensure_ascii=False, default=str)):
                    llm_circuit_breaker.record_success()
                    return {"answer": content, "skills": [fact["skill"] for fact in facts],
                            "tool_result": {"skills": facts},
                            "resolved_context": _extract_context_entities(facts)}
                llm_circuit_breaker.record_failure("empty or ungrounded LLM response")
                return None
            messages.append({"role": "assistant", "content": str(reply.get("content") or ""),
                             "tool_calls": calls})
            if len(calls) == 1:
                fact, tool_msg = _execute_tool_call(skills, calls[0])
                facts.append(fact)
                messages.append(tool_msg)
            else:
                with ThreadPoolExecutor(max_workers=min(len(calls), 6)) as executor:
                    results = list(executor.map(lambda c: _execute_tool_call(skills, c), calls))
                for fact, tool_msg in results:
                    facts.append(fact)
                    messages.append(tool_msg)
        llm_circuit_breaker.record_failure("agent loop exhausted maximum rounds")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        llm_circuit_breaker.record_failure(error)
        return None
    return None
