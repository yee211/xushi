"""接地校验：回答中的事实性声明不得超出工具返回的事实集。

这里收敛原先散落在 loop 与 polish_ai 中的公共校验：
- time_grounded：时间白名单（内容中的 HH:MM 必须来自工具事实或服务端当前时刻）；
- facts_grounded：语义声明校验（课程/同步/天气/同学课表结论必须有工具事实支撑）；
- dates_grounded / teachers_grounded：日期与教师姓名白名单（2026-10 新增盲区补齐）。

宽松是刻意的：白名单只拦编造的时间、日期、教师、教室、课程名与同步/天气结论，
不做全文语义判断；模型基于事实的推算（“还剩 30 分钟”）不应被误杀。
polish 层的“模板事实保留”校验仍在 polish_ai，但常量共享自此模块。
"""
import re
from datetime import date, timedelta

FORBIDDEN_TOKENS = ("user_id", "schedule_id", "sql", "```", "工具结果", "模板答案", "消息时间", "已解析上下文")
TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CN_DATE = re.compile(r"(\d{1,2})月(\d{1,2})[日号]")
_TEACHER_MENTION = re.compile(r"([\u4e00-\u9fa5]{2,4})(?:老师|教授)")


def times_in(value) -> set[str]:
    return {f"{int(hour):02d}:{minute}" for token in TIME_PATTERN.findall(str(value or ""))
            for hour, minute in [token.split(":")]}


def time_grounded(content, context) -> bool:
    """宽松时间校验：拦住编造时间、超长与元信息泄漏。

    合法时间来自工具事实及服务端当前时刻，不包含时区偏移或历史消息时间戳，
    因此模型基于事实做的时间推算（如“还剩 76 分钟”“现在 08:44”）不会被误杀。
    """
    text = str(content or "").strip()
    if not text or len(text) > 4000:
        return False
    if any(token in text.lower() for token in FORBIDDEN_TOKENS):
        return False
    return times_in(text) <= times_in(context)


def _walk(value, visit) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _walk(item, visit)
    elif isinstance(value, list):
        for item in value:
            _walk(item, visit)
    else:
        visit(value)


def dates_grounded(content, facts: list[dict], question: str, today: date) -> bool:
    """内容里的具体日期（ISO 或 “M月D日/号”）必须来自工具事实、用户原话或今天起三天内的相对日。"""
    text = str(content or "")
    allowed_iso: set[str] = set()
    allowed_pairs: set[tuple[int, int]] = set()

    def collect(value):
        if isinstance(value, str) and _ISO_DATE.fullmatch(value):
            allowed_iso.add(value)

    for fact in facts:
        _walk(fact.get("result") or {}, collect)
    for match in _ISO_DATE.findall(question or ""):
        allowed_iso.add(match)
    for offset in (0, 1, 2):
        day = today + timedelta(days=offset)
        allowed_iso.add(day.isoformat())
        allowed_pairs.add((day.month, day.day))
    for month, day in _CN_DATE.findall(question or ""):
        allowed_pairs.add((int(month), int(day)))
    for iso in list(allowed_iso):
        allowed_pairs.add((int(iso[5:7]), int(iso[8:10])))

    for match in _ISO_DATE.findall(text):
        if match not in allowed_iso:
            return False
    for month, day in _CN_DATE.findall(text):
        if (int(month), int(day)) not in allowed_pairs:
            return False
    return True


def teachers_grounded(content, facts: list[dict], question: str) -> bool:
    """带“老师/教授”称谓的姓名必须来自工具事实；复述用户原话中的称谓不算编造。"""
    text = str(content or "")
    mentions = _TEACHER_MENTION.findall(text)
    if not mentions:
        return True
    allowed: set[str] = set()

    def walk_teachers(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"teacher", "display_name"} and isinstance(item, str) and item.strip():
                    allowed.add(item.strip())
                walk_teachers(item)
        elif isinstance(value, list):
            for item in value:
                walk_teachers(item)

    for fact in facts:
        walk_teachers(fact.get("result") or {})
    # 问句捕获可能带前缀字（如“我语文老师”→“我语文”），用子串相容判断复述。
    echoed = set(_TEACHER_MENTION.findall(question or ""))
    return all(any(name == mention or mention.endswith(name) for name in allowed)
               or any(mention in echo or echo in mention for echo in echoed)
               for mention in mentions)


def facts_grounded(content: str, facts: list[dict], question: str, today: date | None = None) -> bool:
    from .other_reply import group_request, mentions_others, render_other_facts
    errors = [f.get("result") or {} for f in facts if (f.get("result") or {}).get("error")]
    if errors and all((f.get("result") or {}).get("error") for f in facts) and any(
            content.strip() == error.get("message") for error in errors):
        return True
    other_answer = render_other_facts(facts, today or date.today())
    if other_answer is not None:
        # These replies have a deterministic layout, including per-person and
        # intersection conclusions. Never validate them against a union of times.
        return content.strip() == other_answer
    if (mentions_others(question) or group_request(question)) and re.search(
            r"有空|空闲|没课|没有课|有.{0,12}课", content) and not any(
            f.get("skill") in {"query_other_day_courses", "check_group_availability",
                               "remove_other_schedule", "clear_other_schedules"} for f in facts):
        return False
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
    course_tools = {
        "query_day_courses", "query_week_courses", "get_next_course", "find_course",
        "query_other_day_courses", "check_group_availability", "list_other_people", "add_other_schedule",
        "remove_other_schedule", "clear_other_schedules",
    }
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
        has_other_meta = False
        for fact in queried:
            result = fact["result"]
            rows.extend(result.get("courses") or [])
            rows.extend(result.get("occurrences") or [])
            if result.get("course"):
                rows.append(result["course"])
            for participant in result.get("participants") or []:
                rows.extend(participant.get("courses") or [])
            if fact["skill"] in {"add_other_schedule", "list_other_people"}:
                has_other_meta = True
            # find_course uses an integer days horizon; weekly queries return a list.
            days = result.get("days")
            for day in days if isinstance(days, list) else []:
                rows.extend(day.get("courses") or [])
        positive = re.sub(r"没有[^，。！？\n]*|没课|不用上课", "", content)
        if not rows and not has_other_meta and re.search(r"有.{0,16}课(?!表)|正在上|下一节是", positive):
            return False
        # A single-day result cannot be rewritten as a blanket no-class conclusion.
        day_results = [f["result"] for f in queried if f["skill"] == "query_day_courses"]
        if len(day_results) == 1 and day_results[0].get("courses") and re.search(
                r"(?:今天|明天|后天|当天)?(?:没有课|没课|全天无课|没有任何课)", content):
            return False
        # Allow room/class/student codes from courses, candidates, and person metadata.
        allowed_rooms = {str(row.get("room") or "") for row in rows}
        for fact in successful:
            res = fact["result"]
            for cand in (res.get("candidates") or []):
                if isinstance(cand, dict):
                    allowed_rooms.update(str(cand.get(k) or "") for k in ("class_name", "student_number_display", "student_id"))
            person = res.get("person")
            if isinstance(person, dict):
                allowed_rooms.update(str(person.get(k) or "") for k in ("class_name", "student_id"))
            # 移除/清空结果里的 removed 元数据（单个 dict 或姓名列表）同样允许被复述。
            removed = res.get("removed")
            if isinstance(removed, dict):
                removed = [removed]
            for item in removed if isinstance(removed, list) else []:
                if isinstance(item, dict):
                    allowed_rooms.update(str(item.get(k) or "") for k in ("class_name", "student_id"))
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
    if not dates_grounded(content, facts, question, today or date.today()):
        return False
    if not teachers_grounded(content, facts, question):
        return False
    return True
