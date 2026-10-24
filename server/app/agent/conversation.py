"""Redis-backed, versioned short conversation history for the schedule agent."""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("agent.conversation")

CLEAN_METADATA_PATTERN = re.compile(r"\s*\[消息时间[:：].*?\]\s*$", re.DOTALL)

# Redis failures degrade silently by design; this flag surfaces the first failure
# (and recovery) so an outage is visible without spamming one warning per call.
_redis_degraded = False


def _note_redis_failure(scope: str) -> None:
    global _redis_degraded
    if not _redis_degraded:
        _redis_degraded = True
        logger.warning("Agent Redis unavailable (%s); history/clarification degrade until it recovers", scope)


def _note_redis_recovery() -> None:
    global _redis_degraded
    if _redis_degraded:
        _redis_degraded = False
        logger.info("Agent Redis recovered")


_APPEND_TURN_LUA = """
local incoming = cjson.decode(ARGV[1])
local current = redis.call('GET', KEYS[1])
local messages = {}
if current then
    local valid, decoded = pcall(cjson.decode, current)
    if valid and type(decoded) == 'table' and type(decoded.messages) == 'table' then
        messages = decoded.messages
    end
end
for _, message in ipairs(incoming.messages) do table.insert(messages, message) end
while #messages > 12 do table.remove(messages, 1) end
incoming.messages = messages
redis.call('SET', KEYS[1], cjson.encode(incoming), 'EX', tonumber(ARGV[2]))
return #messages
"""


def clean_message_content(text: str) -> str:
    return CLEAN_METADATA_PATTERN.sub("", str(text or "")).strip()


def _ttl() -> int:
    return max(300, min(int(os.getenv("AGENT_CONTEXT_TTL_SECONDS", "7200")), 86400))


@lru_cache(maxsize=1)
def _client() -> Redis | None:
    url = os.getenv("AGENT_REDIS_URL", os.getenv("REDIS_URL", "")).strip()
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=1,
                          socket_timeout=1) if url else None


def _key(user_id: int, provider: str, thread_key: str) -> str:
    safe_provider = "".join(character for character in provider if character.isalnum() or character in "-_")
    safe_thread = "".join(character for character in thread_key if character.isalnum() or character in "-_")
    # v2 intentionally abandons histories written by the previous prompt/state logic.
    return f"wx-schedule:agent-context:v2:{safe_provider}:{user_id}:{safe_thread[:128]}"


def load_history(user_id: int, provider: str, thread_key: str, schedule_version: str | None = None) -> list:
    client = _client()
    if client is None:
        return []
    try:
        payload = client.get(_key(user_id, provider, thread_key))
        messages = (json.loads(payload).get("messages") if payload else []) or []
        _note_redis_recovery()
    except (RedisError, ValueError, TypeError):
        _note_redis_failure("load_history")
        return []
    result = []
    for item in messages[-12:]:
        timestamp = item.get("created_at", "")
        resolved = item.get("resolved_context") or {}
        # Active questions have their own scoped state. Never revive an expired
        # or cancelled clarification through the longer general history TTL.
        if resolved.get("awaiting_input"):
            continue
        content = clean_message_content(item.get("content"))
        if schedule_version is not None and item.get("schedule_version") != schedule_version:
            if item.get("role") != "user":
                continue
            resolved = {key: value for key, value in resolved.items()
                        if key in {"intent", "target_date", "period", "weekday", "course_name", "person"}}
            content += "\n[课表已更新：历史消息仅用于理解追问，课程事实必须重新查询]"
        if item.get("role") == "user":
            suffix = f"\n[消息时间：{timestamp}；已解析上下文：{json.dumps(resolved, ensure_ascii=False)}]"
            result.append(HumanMessage(content=content + suffix))
        else:
            result.append(AIMessage(content=content))
    return result


def append_turn(user_id: int, provider: str, thread_key: str, user_text: str,
                answer: str, received_at: datetime, resolved_context: dict, schedule_version: str | None = None) -> None:
    client = _client()
    if client is None:
        return
    key = _key(user_id, provider, thread_key)
    messages = [
        {"role": "user", "content": clean_message_content(user_text), "created_at": received_at.isoformat(),
         "resolved_context": resolved_context, "schedule_version": schedule_version},
        {"role": "assistant", "content": clean_message_content(answer), "created_at": datetime.now(received_at.tzinfo).isoformat(),
         "resolved_context": resolved_context, "schedule_version": schedule_version},
    ]
    payload = {"messages": messages, "state": resolved_context,
               "updated_at": received_at.isoformat(),
               "expires_at": (received_at + timedelta(seconds=_ttl())).isoformat()}
    try:
        client.eval(_APPEND_TURN_LUA, 1, key, json.dumps(payload, ensure_ascii=False), _ttl())
        _note_redis_recovery()
    except RedisError:
        _note_redis_failure("append_turn")
        return


def selected_schedule(user_id: int, provider: str, thread_key: str) -> int | None:
    client = _client()
    if client is None:
        return None
    try:
        value = client.get(_key(user_id, provider, thread_key) + ":selection")
        selected = int(value) if value else None
        _note_redis_recovery()
        return selected
    except (RedisError, ValueError, TypeError):
        _note_redis_failure("selected_schedule")
        return None


def select_schedule(user_id: int, provider: str, thread_key: str, schedule_id: int) -> bool:
    client = _client()
    if client is None:
        return False
    try:
        client.setex(_key(user_id, provider, thread_key) + ":selection", 86400, str(schedule_id))
        _note_redis_recovery()
        return True
    except RedisError:
        _note_redis_failure("select_schedule")
        return False
