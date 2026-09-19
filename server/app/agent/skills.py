"""统一注册的 Agent 技能：名字、描述、JSON 参数与只读处理器放在一起。

LLM 通过 function calling 自主决定调用哪些技能、调用几次；处理器身份由 ScheduleTools
注入，返回纯数据 dict，错误以 {"error": ...} 形式回传给模型自行处理。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type

from ..services.schedule_query import ScheduleQueryError
from ..services.weather import day_rain
from .tools import ScheduleTools


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    parameters: dict
    required: tuple[str, ...]
    handler: Callable[..., dict]


_DATE = {"type": "string", "description": "日期，YYYY-MM-DD"}
_PERIOD = {"type": "string", "enum": ["all", "morning", "afternoon", "evening"],
           "description": "时段：all 全天 / morning 上午 / afternoon 下午 / evening 晚上"}


def build_skills(tools: ScheduleTools) -> list[Skill]:
    """按当前用户上下文实例化技能处理器。"""
    today = tools.context.now.date()

    # 处理器形参名必须与 JSON Schema 属性名一致（dispatch 按 **arguments 展开），
    # 因此用 date_type 别名引用 datetime.date，避免与形参 date 遮蔽冲突。
    def query_day_courses(date: str, period: str = "all") -> dict:
        return tools.get_courses_by_date(date_type.fromisoformat(date), period)

    def query_week_courses(date: str = "") -> dict:
        return tools.get_courses_by_week(date_type.fromisoformat(date) if date else today)

    def get_next_course() -> dict:
        return tools.get_next_course()

    def find_course(name: str, from_date: str = "") -> dict:
        return tools.find_course(name, date_type.fromisoformat(from_date) if from_date else today)

    def list_course_catalog() -> dict:
        return {"courses": tools.list_course_catalog()}

    def get_weather(date: str, period: str = "all") -> dict:
        return {"date": date, "period": period, "rain": day_rain(date_type.fromisoformat(date), period)}

    return [
        Skill("query_day_courses", "查询某一天的课程列表，可按时段过滤",
              {"date": _DATE, "period": _PERIOD}, ("date",), query_day_courses),
        Skill("query_week_courses", "查询某一自然周（周一到周日）的每日课程，默认本周",
              {"date": {**_DATE, "description": "周内任意一天，YYYY-MM-DD，可空表示本周"}}, (), query_week_courses),
        Skill("get_next_course", "查询下一节课或正在上的课（未来 7 天内）", {}, (), get_next_course),
        Skill("find_course", "按课程名查询未来的上课时间、教室与教师",
              {"name": {"type": "string", "description": "课程名或简称"},
               "from_date": {**_DATE, "description": "起始日期，可空表示今天"}}, ("name",), find_course),
        Skill("list_course_catalog", "列出该用户课表里的全部课程候选，用于把简称/口语对照成完整课程名",
              {}, (), list_course_catalog),
        Skill("get_weather", "查询某天（可限定时段）的降雨情况，用于回答天气或要不要带伞",
              {"date": _DATE, "period": _PERIOD}, ("date",), get_weather),
    ]


def openai_tools(skills: list[Skill]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": skill.name, "description": skill.description,
                          "parameters": {"type": "object", "properties": skill.parameters,
                                         "required": list(skill.required)}}}
            for skill in skills]


def dispatch(skills: list[Skill], name: str, arguments_json: str) -> dict:
    """执行一次技能调用；任何失败都折叠成 {"error": ...} 交回模型，不让异常逃出循环。"""
    skill = next((item for item in skills if item.name == name), None)
    if skill is None:
        return {"error": f"未知技能：{name}"}
    try:
        arguments = json.loads(arguments_json or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("参数必须是对象")
        missing = [key for key in skill.required if key not in arguments]
        if missing:
            return {"error": f"缺少必填参数：{'、'.join(missing)}"}
        return skill.handler(**arguments)
    except ScheduleQueryError as error:
        return {"error": error.code, "message": error.message}
    except (ValueError, TypeError) as error:
        return {"error": f"参数不合法：{error}"}
