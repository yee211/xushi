"""Per-turn agent telemetry: which path answered, how many model calls, token usage.

Stats ride a ContextVar so every layer (graph nodes, fallback, http_client) can
annotate the same turn without threading a parameter through call signatures.
No user content is ever recorded—only counters and enum-like labels.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TurnStats:
    path: str = ""        # sync | status | llm | fallback
    outcome: str = ""     # ok | rejected | rounds_exhausted | truncated | recovered | error | llm_unavailable
    rounds: int = 0       # model rounds used by the agent loop
    llm_calls: int = 0    # provider round-trips this turn (loop + fallback extract/polish/small_talk)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    tool_errors: list = field(default_factory=list)  # 去重后的工具错误码（如 connection_not_configured）


_stats: ContextVar[TurnStats | None] = ContextVar("agent_turn_stats", default=None)


def start_turn() -> None:
    _stats.set(TurnStats())


def active() -> TurnStats | None:
    return _stats.get()


def note(path: str | None = None, outcome: str | None = None, rounds: int | None = None) -> None:
    stats = _stats.get()
    if stats is None:
        return
    if path is not None:
        stats.path = path
    if outcome is not None:
        stats.outcome = outcome
    if rounds is not None:
        stats.rounds = rounds


def note_tool_errors(tool_result) -> None:
    """从一轮的工具事实中提取去重错误码；只记枚举值，不记用户内容。"""
    stats = _stats.get()
    if stats is None or not isinstance(tool_result, dict):
        return
    for fact in tool_result.get("skills") or []:
        item = fact.get("result") if isinstance(fact, dict) else None
        if isinstance(item, dict):
            code = item.get("error")
            if code and code not in stats.tool_errors:
                stats.tool_errors.append(str(code)[:48])
                if len(stats.tool_errors) >= 5:
                    return


def record_llm_call(response) -> None:
    """Count one provider call and, when the provider reports it, accumulate usage."""
    stats = _stats.get()
    if stats is None:
        return
    stats.llm_calls += 1
    try:
        usage = (response.json() or {}).get("usage")
    except Exception:
        return
    if not isinstance(usage, dict):
        return
    stats.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    stats.completion_tokens += int(usage.get("completion_tokens") or 0)
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        stats.cached_tokens += int(details.get("cached_tokens") or 0)
