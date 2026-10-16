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


class PendingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=4000)
    version: str
    created_at: datetime
    turns: list[tuple[str, str]] = Field(default_factory=list, max_length=3)
    schedules: list[Choice] = Field(default_factory=list, max_length=30)

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
            return None
        pending = PendingQuestion.model_validate_json(raw)
        if (
            pending.version != version
            or pending.created_at.tzinfo is None
            or not timedelta(0) <= now - pending.created_at < timedelta(seconds=TTL)
        ):
            clear(scope)
            return None
        return pending
    except (RedisError, ValueError, TypeError, ValidationError):
        return None


def clear(scope):
    client = conversation._client()
    if client is not None:
        try:
            client.setex(key(*scope), 1, "")
        except RedisError:
            pass


def save(scope, pending):
    client = conversation._client()
    if client is None:
        return False
    try:
        client.setex(key(*scope), TTL, pending.model_dump_json())
        return True
    except RedisError:
        return False


def schedule_choices(result):
    error = result.get("error") or {}
    errors = [error] + [(f.get("result") or {}) for f in (result.get("tool_result") or {}).get("skills", [])]
    for item in errors:
        if item.get("code", item.get("error")) == "AMBIGUOUS_SCHEDULE":
            return [Choice.model_validate(c) for c in item.get("candidates", [])][:30]
    return []


def selected_choice(pending, text):
    text = text.strip(" ，,。！!？?")
    explicit = re.fullmatch(r"使用课表\s*(\d+)", text)
    if explicit:
        return next((c for c in pending.schedules if c.id == int(explicit[1])), None)
    ordinal = re.fullmatch(r"第?([一二三四五六七八九十]|\d+)(?:个|张|份)?", text)
    if ordinal:
        value = ordinal[1]
        index = int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1
        return pending.schedules[index - 1] if 1 <= index <= len(pending.schedules) else None
    matches = [c for c in pending.schedules if c.name == text]
    return matches[0] if len(matches) == 1 else None


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
