"""LangGraph 查询入口及共享的工具执行辅助函数。

没有意图枚举、没有闲聊分支——一切由模型决定是否调技能以及如何作答。
最终回答需通过接地校验（实现见 grounding.py，这里保留 _grounded/_facts_grounded 别名），
LLM 不可用、轮次耗尽或校验失败时返回 None，由调用方退回确定性模板路径。
"""

import json
import logging
import os

from ..services.llm_config import get_llm_config as get_llm_config
from .budget import execution
from .budget import remaining as remaining
from .circuit_breaker import llm_circuit_breaker
from .grounding import facts_grounded as _facts_grounded  # noqa: F401  兼容历史调用的再导出
from .grounding import time_grounded as _grounded  # noqa: F401
from .http_client import post_llm
from .intent_ai import agent_config as agent_config
from .polish_ai import _api_messages as _api_messages
from .prompts import FORMAT_RULES
from .skills import build_skills as build_skills
from .skills import dispatch
from .skills import openai_tools as openai_tools


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
- 只问自己有没有空/空档用 query_day_courses；涉及他人、谁有空或共同空闲必须用 check_group_availability。
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
""" + FORMAT_RULES + """
技能返回 error 时如实说明，不要猜测或虚构数据。"""


def _timeout() -> float:
    return max(3.0, min(float(os.getenv("AGENT_TIMEOUT_SECONDS", "15")), 30.0))


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
            if "person" in args and "person" not in resolved and args["person"]:
                resolved["person"] = str(args["person"])
    return resolved


def run(tools, message: str, history: list | None = None) -> dict | None:
    try:
        with execution():
            from .graph import run as run_graph
            return run_graph(tools, message, history)
    except Exception as error:
        logger.warning("Agent failed: %s", type(error).__name__)
        from . import telemetry
        telemetry.note(outcome="error")
        llm_circuit_breaker.record_failure(error)
        return None
    finally:
        from .circuit_breaker import CircuitState
        if llm_circuit_breaker.state == CircuitState.HALF_OPEN:
            llm_circuit_breaker.record_failure("probe exited without a result")
