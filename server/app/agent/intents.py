"""意图枚举与必备技能映射：规则解析、LLM 意图提取与图校验共用这一份定义。

新增意图或调整“某意图至少要调用哪些技能”时只改这里；
orchestrator.parse_intent / intent_ai / graph.validate 均从这里读取。
"""

INTENTS = ("QUERY_DAY", "QUERY_WEEK", "QUERY_NEXT", "QUERY_AVAILABILITY", "QUERY_COURSE_ON_DAY",
           "QUERY_WEATHER", "FIND_COURSE", "HELP")

# 图校验用：命中该意图时，技能集至少要包含其中之一；无映射的意图（HELP 等）不强制。
REQUIRED_SKILLS: dict[str, set[str]] = {
    "QUERY_DAY": {"query_day_courses", "query_other_day_courses"},
    "QUERY_AVAILABILITY": {"query_day_courses", "query_other_day_courses", "check_group_availability"},
    "QUERY_COURSE_ON_DAY": {"query_day_courses", "query_other_day_courses"},
    "QUERY_WEEK": {"query_week_courses"},
    "QUERY_NEXT": {"get_next_course"},
    "FIND_COURSE": {"find_course"},
    "QUERY_WEATHER": {"get_weather"},
}
