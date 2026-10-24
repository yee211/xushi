"""Short-lived, channel-scoped questions awaiting a user answer."""

import hashlib
import re
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from . import conversation

TTL = 900


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)


class PersonChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    student_id: str
    name: str = ""
    class_name: str = ""
    student_number_display: str = ""


class PendingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=4000)
    version: str
    created_at: datetime
    turns: list[tuple[str, str]] = Field(default_factory=list, max_length=3)
    schedules: list[Choice] = Field(default_factory=list, max_length=30)
    courses: list[Choice] = Field(default_factory=list, max_length=30)
    people: list[PersonChoice] = Field(default_factory=list, max_length=8)
    person_request: dict = Field(default_factory=dict)
    clear_student_ids: list[str] = Field(default_factory=list, max_length=50)
    course_query: str = Field(default="", max_length=80)

    def history(self):
        result = [HumanMessage(content=self.original + "\n[消息时间：" + self.created_at.isoformat() + "]")]
        for question, answer in self.turns:
            result.extend([AIMessage(content=question), HumanMessage(content=answer)])
        return result + [AIMessage(content=self.question)]


def key(user_id, provider, sender, account):
    # Hash raw fields to avoid collisions between sanitized account/sender IDs.
    scope = hashlib.sha256(str((provider, sender, account)).encode()).hexdigest()
    return f"wx-schedule:agent-clarification:v1:{user_id}:{scope}"


def load(scope, version, now):
    client = conversation._client()
    if client is None or version is None:
        return None
    try:
        raw = client.get(key(*scope))
        if not raw:
            conversation._note_redis_recovery()
            return None
        pending = PendingQuestion.model_validate_json(raw)
        if (
            pending.version != version
            or pending.created_at.tzinfo is None
            or not timedelta(0) <= now - pending.created_at < timedelta(seconds=TTL)
        ):
            clear(scope)
            conversation._note_redis_recovery()
            return None
        conversation._note_redis_recovery()
        return pending
    except (RedisError, ValueError, TypeError, ValidationError):
        conversation._note_redis_failure("clarification.load")
        return None


def clear(scope):
    client = conversation._client()
    if client is not None:
        try:
            client.setex(key(*scope), 1, "")
            conversation._note_redis_recovery()
        except RedisError:
            conversation._note_redis_failure("clarification.clear")


def save(scope, pending):
    client = conversation._client()
    if client is None:
        return False
    try:
        client.setex(key(*scope), TTL, pending.model_dump_json())
        conversation._note_redis_recovery()
        return True
    except RedisError:
        conversation._note_redis_failure("clarification.save")
        return False


def schedule_choices(result):
    error = result.get("error") or {}
    errors = [error] + [(f.get("result") or {}) for f in (result.get("tool_result") or {}).get("skills", [])]
    for item in errors:
        if item.get("code", item.get("error")) == "AMBIGUOUS_SCHEDULE":
            return [Choice.model_validate(c) for c in item.get("candidates", [])][:30]
    return []


def person_choices(result):
    """提取候选与回放参数；add 走 ambiguous 返回，remove 走折叠的 AMBIGUOUS_PERSON 错误。"""
    import json
    for fact in reversed((result.get("tool_result") or {}).get("skills", [])):
        item = fact.get("result") or {}
        if not ((fact.get("skill") == "add_other_schedule" and item.get("status") == "ambiguous")
                or (fact.get("skill") == "remove_other_schedule" and item.get("error") == "AMBIGUOUS_PERSON")):
            continue
        args = fact.get("arguments") or {}
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except (ValueError, TypeError):
            continue
        if not isinstance(args, dict):
            continue
        if fact.get("skill") == "add_other_schedule" and item.get("status") == "ambiguous":
            return ([PersonChoice.model_validate(c) for c in item["candidates"][:8]],
                    {k: v for k, v in args.items() if k in {"keyword", "remark", "term"}})
        if fact.get("skill") == "remove_other_schedule" and item.get("error") == "AMBIGUOUS_PERSON":
            return ([PersonChoice.model_validate(c) for c in (item.get("candidates") or [])[:8]],
                    {"action": "remove", **{k: v for k, v in args.items() if k in {"person"}}})
    return [], {}


def course_choices(result):
    """从课程歧义结果提取候选与用户口语原词，供序号选择后回放原问题。"""
    match = (result.get("tool_result") or {}).get("course_match") or {}
    if match.get("status") != "ambiguous":
        return [], ""
    choices = []
    for index, item in enumerate((match.get("candidates") or [])[:30]):
        course_id = item.get("course_id") if isinstance(item.get("course_id"), int) else item.get("id")
        choices.append(Choice(id=course_id if isinstance(course_id, int) and course_id > 0 else index + 1,
                              name=str(item.get("name") or f"课程{index + 1}")[:200]))
    query = str((result.get("resolved_context") or {}).get("course_name") or "")
    return choices, query[:80]


def substitute_course(original: str, query: str, name: str) -> str:
    """把原问题里的口语课程名替换为选定的完整课程名；原词定位不到时直接点名。"""
    if query and query in original:
        return original.replace(query, name, 1)
    return f"{original}（指{name}）"


def selected_person(pending, text):
    text = text.strip(" ，,。！!？?")
    # 读音兜底等场景常只剩一位候选，“是/对/确认”即选定，不必再报序号。
    if len(pending.people) == 1 and text in {
            "是", "对", "是的", "对的", "嗯", "嗯嗯", "好", "好的", "确认", "没错", "就这个", "就是他", "就是她"}:
        return pending.people[0]
    ordinal = re.fullmatch(r"第?([一二三四五六七八]|\d+)(?:个|位|名)?", text)
    if ordinal:
        value = ordinal[1]
        index = int(value) if value.isdigit() else "一二三四五六七八".index(value) + 1
        return pending.people[index - 1] if 1 <= index <= len(pending.people) else None
    matches = [p for p in pending.people if text in {
        p.student_id, p.name, p.class_name, p.student_number_display, p.class_name + "那个"}]
    if matches:
        return matches[0] if len(matches) == 1 else None

    def class_text(value):
        value = re.sub(r"\s+", "", value)
        return re.sub(r"(?:的那个|的那位|那个|那位|这个|这位|的)$", "", value)

    needle = class_text(text)
    if not needle:
        return None
    # 先保留用户明确指定的年级；只有用户省略年级时才允许省略候选的年级前缀。
    matches = [p for p in pending.people if class_text(p.class_name) == needle]
    if not matches and not re.match(r"\d", needle):
        matches = [p for p in pending.people if re.sub(
            r"^(?:20\d{2}|\d{2})(?:级)?(?=\D)", "", class_text(p.class_name)) == needle]
    return matches[0] if len(matches) == 1 else None


def pick_choice(choices: list[Choice], text: str):
    """在给定候选里解析用户回复：序号（“第二门”）、“使用课表 N”或完整名称。"""
    text = text.strip(" ，,。！!？?")
    explicit = re.fullmatch(r"使用课表\s*(\d+)", text)
    if explicit:
        return next((c for c in choices if c.id == int(explicit[1])), None)
    ordinal = re.fullmatch(r"第?([一二三四五六七八九十]|\d+)(?:个|张|份|门|位)?", text)
    if ordinal:
        value = ordinal[1]
        index = int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1
        return choices[index - 1] if 1 <= index <= len(choices) else None
    matches = [c for c in choices if c.name == text]
    return matches[0] if len(matches) == 1 else None


def selected_choice(pending, text):
    return pick_choice(pending.schedules, text)


def is_new_request(text, today):
    from .orchestrator import is_date_only, parse_intent
    from .sync import requested, status_requested

    if is_date_only(re.sub(r"\s+", "", text)):
        return False
    return (
        requested(text)
        or status_requested(text)
        or parse_intent(text, today).name != "HELP"
        or bool(re.fullmatch(r"你好|您好|嗨|谢谢|再见", text))
        or bool(re.match(r"另外|换个问题|重新开始", text))
    )


def resume_text(pending, text):
    # Date-only answers also work during a model outage. Preserve the original
    # query and replace its date expression rather than treating the reply as chat.
    date_word = r"今天|今日|明天|明日|后天|(?:下下|上|下|本|这)?(?:周|星期)[一二三四五六日天]"
    if re.fullmatch("(?:" + date_word + ")(?:上午|下午|晚上)?[。！!]?", text):
        original = pending.original
        replacement = re.sub("(?:" + date_word + ")(?:上午|下午|晚上)?", lambda m: text.rstrip("。！!"), original)
        return replacement if replacement != original else text.rstrip("。！!") + "，" + original
    return text
