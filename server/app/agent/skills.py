"""统一注册的 Agent 技能：名字、描述、JSON 参数与只读处理器放在一起。

LLM 通过 function calling 自主决定调用哪些技能、调用几次；处理器身份由 ScheduleTools
注入，返回纯数据 dict，错误以 {"error": ...} 形式回传给模型自行处理。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type

from ..services.schedule_query import ScheduleQueryError
from ..services.weather import day_rain, fetch_daily_weather
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
        target = date_type.fromisoformat(date)
        if period not in {"all", "morning", "afternoon", "evening"}:
            raise ValueError("无效的时间段")
        return {"date": date, "period": period, "rain": day_rain(target, period),
                "daily": fetch_daily_weather(target)}

    def list_other_people() -> dict:
        return tools.list_other_people()

    def query_other_day_courses(person: str, date: str, period: str = "all") -> dict:
        return tools.query_other_day_courses(person, date_type.fromisoformat(date), period)

    def check_group_availability(date: str, period: str = "all",
                                 people: list[str] | None = None, include_me: bool = True) -> dict:
        return tools.check_group_availability(date_type.fromisoformat(date), period, people, bool(include_me))

    def compare_other_week_courses(person: str, date: str) -> dict:
        return tools.compare_other_week_courses(person, date_type.fromisoformat(date))

    def add_other_schedule(keyword: str = "", remark: str | None = None, term: str = "", student_id: str = "") -> dict:
        return tools.add_other_schedule(keyword, remark, term, student_id)

    def remove_other_schedule(person: str = "", student_id: str = "") -> dict:
        return tools.remove_other_schedule(person, student_id)

    def clear_other_schedules(confirm: bool = False, expected_count: int | None = None) -> dict:
        return tools.clear_other_schedules(confirm, expected_count)

    return [
        Skill("get_other_schedule_status", "查询同学课表后台同步任务进度，不查询自己的同步任务，不发起同步",
              {}, (), tools.get_other_schedule_status),
        Skill("sync_other_schedule", "同步已保存的一位同学课表，按姓名或唯一备注定位；只提交后台任务，不代表完成；不修改自己的课表",
              {"person": {"type": "string", "description": "已保存同学的姓名或唯一备注"}},
              ("person",), tools.sync_other_schedule),
        Skill("sync_all_other_schedules", "同步全部已保存同学课表，不含自己的课表；只提交后台任务，不代表完成",
              {}, (), tools.sync_all_other_schedules),
        Skill("sync_schedule", "仅同步用户自己的课表，不包含同学；仅在用户明确要求同步/更新课表时提交后台任务；立即返回，不能代表同步完成",
              {}, (), tools.sync_schedule),
        Skill("get_schedule_status", "查询已导入课表、学校绑定、最近同步时间和同步任务进度；不发起同步",
              {}, (), tools.get_schedule_status),
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
        Skill("get_weather", "查询某天天气概况、最高最低温度及指定时段降雨；daily 是全天概况，rain 是所选时段降雨",
              {"date": _DATE, "period": _PERIOD}, ("date",), get_weather),
        Skill("list_other_people", "列出当前用户已保存的同学课表名单（含备注、姓名、班级、学期）",
              {}, (), list_other_people),
        Skill("query_other_day_courses", "查询已保存的某位同学/室友在某一天的课程列表（按备注或姓名匹配）",
              {"person": {"type": "string", "description": "同学备注（如“室友”）或姓名（如“张三”）"},
               "date": _DATE, "period": _PERIOD}, ("person", "date"), query_other_day_courses),
        Skill("compare_other_week_courses", "比较某位已保存同学与我在某一自然周的课程差异，例如某某下周有什么课和我不一样；返回双方不同的课程，不能用共同空闲替代",
              {"person": {"type": "string", "description": "同学姓名或备注"},
               "date": {**_DATE, "description": "目标周内任意一天，YYYY-MM-DD"}},
              ("person", "date"), compare_other_week_courses),
        Skill("check_group_availability", "查询某天某时段谁有空、或者我与已保存同学的共同空闲时间段",
              {"date": _DATE, "period": _PERIOD,
               "people": {"type": "array", "items": {"type": "string"},
                          "description": "指定要比较的同学备注或姓名列表；留空或省略表示比较全部已保存的同学"},
               "include_me": {"type": "boolean", "description": "是否把用户自己的课表也纳入共同空闲比对，默认 true；仅问“同学中谁有空”时可设为 false"}},
              ("date",), check_group_availability),
        Skill("add_other_schedule", "从学校名录搜索并保存同学课表到“同学课表”列表（支持姓名、班级、年级或学号关键词；若同名多人会返回候选列表）",
              {"keyword": {"type": "string", "description": "搜索关键词，如姓名“张三”或“24级软件1班张三”"},
               "remark": {"type": "string", "description": "可选备注，如“室友”、“搭子”"},
               "term": {"type": "string", "description": "可选学期，如 2025-2026-2，留空自动使用当前学期"},
               "student_id": {"type": "string", "description": "可选学生唯一ID（从多候选确认时传入）"}},
              (), add_other_schedule),
        Skill("remove_other_schedule", "从已保存的“同学课表”名单中移除某位同学（按备注或姓名匹配；未保存或匹配多人时返回候选与提示；不影响用户自己的课表）",
              {"person": {"type": "string", "description": "同学备注（如“室友”）或姓名（如“张三”）"},
               "student_id": {"type": "string", "description": "可选学生唯一ID（从候选确认时传入）"}},
              (), remove_other_schedule),
        Skill("clear_other_schedules", "清空全部已保存的同学课表。首次调用必须不带 confirm（或 false），把返回的待确认名单原样转达用户；仅当用户明确回复确认后才带 confirm=true 并把返回的 count 原样作为 expected_count 再次调用执行；用户否定或改口时不得执行",
              {"confirm": {"type": "boolean", "description": "用户已明确确认清空时为 true，否则省略或 false"},
               "expected_count": {"type": "integer", "description": "待确认结果返回的人数 count，确认执行时原样传入"}},
              (), clear_other_schedules),
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
        return {"error": error.code, "message": error.message,
                **({"candidates": error.candidates} if error.candidates else {})}
    except (ValueError, TypeError) as error:
        return {"error": f"参数不合法：{error}"}
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Agent skill failed: %s", name)
        return {"error": "service_unavailable", "message": "查询服务暂不可用，请稍后重试"}
