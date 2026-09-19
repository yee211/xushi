"""可选的 LLM 回答润色层：把模板事实答案口语化；输出必须通过接地校验，否则调用方退回模板。

与意图提取共用 AGENT_*/AI_* 配置；未配置或调用失败时返回 None，链路行为与纯模板完全一致。
"""
import json
import os
import re
from collections.abc import Mapping

import httpx

from ..services.llm_config import get_llm_config
from .http_client import get_llm_client, is_httpx_post_patched
from .intent_ai import agent_config


def _post_llm(url: str, **kwargs):
    if is_httpx_post_patched():
        return httpx.post(url, **kwargs)
    return get_llm_client().post(url, **kwargs)

TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")
FORBIDDEN_TOKENS = ("user_id", "schedule_id", "sql", "```", "工具结果", "模板答案", "消息时间", "已解析上下文")
COURSE_CLAIM_PATTERN = re.compile(r"有[^，。！？\n]{1,12}课")
HISTORY_TURNS = 6

POLISH_SYSTEM_PROMPT = """你是课表小程序「序时」的课表助手（身份是真诚、靠谱、温和的大学同学）。根据用户消息、模板答案和工具结果，把模板答案改写成一条自然、简练、真诚舒适的中文回复：
- 先直接回答用户问的核心问题，再按需补充细节，不要把工具结果原样罗列；
- 只能使用模板答案和工具结果中出现的事实（课程、时间、节次、教室、教师、日期），严禁新增、修改或推测任何课程信息，严禁丢失“没有课/没有X课”这类否定结论；
- 保留关键信息：列出的每门课都要带上时间、教室、教师；教师姓名照抄返回值，不要添加“老师”等称谓；
- 语气平实真诚，像靠谱的同门同学，不要客服套话（“好的”“亲”），不要油腔滑调或刻意逗趣；
- 表情符号（Emoji）按情绪与场景动态变换（严禁使用“😂”笑哭表情，每次最多 1 个，非必要不加）：
  - 早八 / 赖床 / 犯困：🥱、🛌、☕、💤、⏰
  - 调侃 / 看戏 / 震惊：👀、🌚、🤔、🤐、🫡
  - 催赶课 / 打气 / 劝学：🏃、🎒、💨、📚、🔥
  - 头大 / 崩溃 / 纠结：🤯、🫠、🤦、🥶
  - 下课 / 轻松 / 庆祝：🎉、🥤、✨、😎
- 严禁输出 [消息时间...] 或已解析上下文等系统内部标记；
- 整体不超过 150 字，只输出回复正文，不要解释。没有把握时原样输出模板答案。"""

SMALL_TALK_SYSTEM_PROMPT = """你是课表小程序「序时」的课表助手，身份是真诚、温和、靠谱的大学同学。用户的消息不是具体的课表或天气查询（闲聊、问候、吐槽、纠结旷课等）。
像正常靠谱的同学一样自然回复（一到两句话），态度温和真诚，不生硬免责，也不要油腔滑调、强行逗笑。
表情按情绪场景动态变换（严禁使用“😂”，最多1个，非必要不加）：早八犯困用 🥱/🛌/☕，调侃看戏用 👀/🤔/🫡，催课打气用 🏃/📚/🔥，崩溃纠结用 🤯/🫠/🤦，下课轻松用 🎉/🥤/✨。
顺势可以自然提醒对方能查的事：今天/明天有什么课、这周课表、下一节课、某门课什么时候上。
问天气时结合课表提醒，笼统问法建议带上日期。
不要编造任何课程、时间、地点或天气。只输出回复正文，严禁输出任何系统调试标记。"""


def _api_messages(system_prompt: str, history: list | None, user_content: str) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    # History is stored as individual user/assistant messages, so one turn is two
    # entries. Keep six complete conversational turns rather than six messages.
    for item in (history or [])[-HISTORY_TURNS * 2:]:
        role = {"human": "user", "ai": "assistant"}.get(getattr(item, "type", ""))
        if role:
            messages.append({"role": role, "content": str(getattr(item, "content", ""))})
    messages.append({"role": "user", "content": user_content})
    return messages


def _timeout() -> float:
    return max(2.0, min(float(os.getenv("POLISH_TIMEOUT_SECONDS", "6")), 15.0))


def _fact_values(tool_result, keys: set[str]) -> set[str]:
    """递归收集工具结果里指定键的字符串值，作为接地校验的事实集。"""
    found: set[str] = set()

    def walk(value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in keys and isinstance(item, str) and item.strip():
                    found.add(item.strip())
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(tool_result)
    return found


def _grounded(polished: str, answer: str, tool_result) -> bool:
    """宽松接地校验：拦住编造时间、丢失否定结论、凭空宣称有课、超长与元信息泄漏。"""
    text = str(polished or "").strip()
    if not text or len(text) > max(400, len(answer) * 3):
        return False
    lowered = text.lower()
    if any(token in lowered for token in FORBIDDEN_TOKENS):
        return False
    fact_times = {match for value in _fact_values(tool_result, {"start_time", "end_time"}) | {answer}
                  for match in TIME_PATTERN.findall(value)}
    if not set(TIME_PATTERN.findall(text)) <= fact_times:
        return False
    has_courses = bool(_fact_values(tool_result, {"name"}))
    if has_courses and TIME_PATTERN.search(answer) and not TIME_PATTERN.search(text):
        return False  # 列表型答案不能把所有时间都润色没了
    if "没有" in answer and "没有" not in text:
        return False
    if "带伞" in answer and "伞" not in text:
        return False  # 天气提醒不能被润色丢掉
    if not has_courses and "没有" not in text and COURSE_CLAIM_PATTERN.search(text):
        return False  # 事实里没有任何课程时不得宣称有课
    return True


def polish_config() -> tuple[str, str, str, float, int, bool]:
    config = get_llm_config("polish")
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    api_key = (config.get("api_key") or "").strip()
    model = (config.get("model") or "").strip()
    if not (base_url and api_key and model):
        agent_base, agent_key, agent_mod = agent_config()
        base_url = base_url or agent_base
        api_key = api_key or agent_key
        model = model or agent_mod
    timeout = float(config.get("timeout_seconds") or _timeout())
    max_tokens = int(config.get("max_tokens") or 400)
    enable_thinking = bool(config.get("enable_thinking", False))
    return base_url, api_key, model, timeout, max_tokens, enable_thinking


def polish_answer(message: str, answer: str, tool_result, history: list | None = None,
                  now=None) -> str | None:
    """把模板答案口语化；返回 None 表示保持模板不动。"""
    base_url, api_key, model, timeout, max_tokens, enable_thinking = polish_config()
    if not (base_url and api_key and model):
        return None
    payload = json.dumps({"服务端时间": now.isoformat() if now else "", "用户消息": message,
                          "模板答案": answer, "工具结果": tool_result},
                         ensure_ascii=False, default=str)
    try:
        response = _post_llm(
            f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            json={"model": model, "temperature": 0.2, "max_tokens": max_tokens,
                  "enable_thinking": enable_thinking,
                  "messages": _api_messages(POLISH_SYSTEM_PROMPT, history, payload)})
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        text = re.sub(r"\s*\[消息时间[:：].*?\]\s*$", "", text, flags=re.DOTALL).strip()
        text = text.replace("😂", "").strip()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if text and text != answer and _grounded(text, answer, tool_result):
        return text
    return None


def small_talk(message: str, history: list | None = None) -> str | None:
    """闲聊/HELP 的简短 LLM 回应；返回 None 时调用方使用固定帮助文案。"""
    base_url, api_key, model, timeout, _, enable_thinking = polish_config()
    if not (base_url and api_key and model):
        return None
    try:
        response = _post_llm(
            f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            json={"model": model, "temperature": 0.5, "max_tokens": 120,
                  "enable_thinking": enable_thinking,
                  "messages": _api_messages(SMALL_TALK_SYSTEM_PROMPT, history, message)})
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        text = re.sub(r"\s*\[消息时间[:：].*?\]\s*$", "", text, flags=re.DOTALL).strip()
        text = text.replace("😂", "").strip()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if text and len(text) <= 300 and not any(token in text.lower() for token in FORBIDDEN_TOKENS):
        return text
    return None

