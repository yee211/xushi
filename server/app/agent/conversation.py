"""Redis-backed, versioned short conversation history for the schedule agent."""

import json
import os
import re
from datetime import datetime, timedelta
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage
from redis import Redis
from redis.exceptions import RedisError

CLEAN_METADATA_PATTERN = re.compile(r"\s*\[消息时间[:：].*?\]\s*$", re.DOTALL)


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


def load_history(user_id: int, provider: str, thread_key: str) -> list:
    client = _client()
    if client is None:
        return []
    try:
        payload = client.get(_key(user_id, provider, thread_key))
        messages = (json.loads(payload).get("messages") if payload else []) or []
    except (RedisError, ValueError, TypeError):
        return []
    result = []
    for item in messages[-12:]:
        timestamp = item.get("created_at", "")
        resolved = item.get("resolved_context") or {}
        content = clean_message_content(item.get("content"))
        if item.get("role") == "user":
            suffix = f"\n[消息时间：{timestamp}；已解析上下文：{json.dumps(resolved, ensure_ascii=False)}]"
            result.append(HumanMessage(content=content + suffix))
        else:
            result.append(AIMessage(content=content))
    return result


def append_turn(user_id: int, provider: str, thread_key: str, user_text: str,
                answer: str, received_at: datetime, resolved_context: dict) -> None:
    client = _client()
    if client is None:
        return
    key = _key(user_id, provider, thread_key)
    try:
        current = client.get(key)
        messages = list((json.loads(current).get("messages") if current else []) or [])
    except (RedisError, ValueError, TypeError):
        messages = []
    messages.extend([
        {"role": "user", "content": clean_message_content(user_text), "created_at": received_at.isoformat(),
         "resolved_context": resolved_context},
        {"role": "assistant", "content": clean_message_content(answer), "created_at": datetime.now(received_at.tzinfo).isoformat(),
         "resolved_context": resolved_context},
    ])
    payload = {"messages": messages[-12:], "state": resolved_context,
               "updated_at": received_at.isoformat(),
               "expires_at": (received_at + timedelta(seconds=_ttl())).isoformat()}
    try:
        client.setex(key, _ttl(), json.dumps(payload, ensure_ascii=False))
    except RedisError:
        return
