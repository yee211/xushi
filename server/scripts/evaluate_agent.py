"""Evaluate the real Agent loop against synthetic timetable/weather fixtures.
Only --live calls the configured model; no user database, Redis or Weixin access.
"""
import argparse
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from scripts.eval_quality import grade, read_cases, write_report

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "evals/agent_cases.jsonl"

def tool_contract(facts, case):
    names = {f["skill"] for f in facts}
    alternatives = case.get("tool_sets", [])
    names_ok = any(set(expected) <= names for expected in alternatives) if alternatives else not names
    args_ok = all(any(f["skill"] == expected["tool"] and
                      all(json.loads(f["arguments"]).get(k) == v for k, v in expected["args"].items())
                      for f in facts) for expected in case.get("arguments", []))
    identity_ok = all(not ({"user_id", "schedule_id"} & set(json.loads(f["arguments"]))) for f in facts)
    return names_ok and args_ok and identity_ok

def fixture_tools(kind="normal"):
    from app.agent.tools import AgentContext, ScheduleTools
    from app.services.schedule_query import teaching_week

    class Result:
        def __init__(self, rows):
            self.rows = rows
        def fetchall(self):
            return self.rows

    class Database:
        def execute(self, sql, params):
            schedule = {"id": 1, "user_id": 1, "name": "评测课表", "term": "2026秋",
                        "start_date": date(2026, 9, 7), "end_date": date(2027, 1, 24),
                        "variant_type": "original", "source_schedule_id": None}
            if "FROM schedules" in sql:
                active = kind != "missing" and teaching_week(schedule, params[1]) is not None
                return Result([schedule] if active else [])
            if "FROM courses" in sql:
                rows = [
                    (1, "大学英语", "李明", "B202", 2, 1, 2),
                    (2, "高等数学", "张华", "A101", 3, 5, 6),
                    (3, "计算机组成原理", "王林", "C303", 3, 7, 8),
                    (4, "大学体育", "赵青", "操场", 5, 3, 4),
                ]
                return Result([{"id": cid, "name": name, "teacher": teacher, "room": room,
                                "weekday": day, "start_section": start, "end_section": end,
                                "weeks": list(range(1, 21))} for cid, name, teacher, room, day, start, end in rows]
                              if kind != "empty" else [])
            if "FROM course_adjustments" in sql:
                return Result([])
            raise AssertionError("Unexpected fixture query")

    now = datetime.fromisoformat("2026-09-08T13:00:00+08:00")
    return ScheduleTools(Database(), AgentContext(1, now))

def evaluate_case(case):
    from langchain_core.messages import AIMessage, HumanMessage

    from app.agent import loop, skills
    from app.agent.circuit_breaker import llm_circuit_breaker
    from app.agent.http_client import close_llm_client

    tools = fixture_tools(case.get("fixture", "normal"))
    config = tuple(os.getenv(name, "").strip().rstrip("/") if name.endswith("URL")
                   else os.getenv(name, "").strip()
                   for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL"))
    if not all(config):
        raise ValueError("Set AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL")
    history = [(HumanMessage if h["role"] == "user" else AIMessage)(content=h["content"])
               for h in case.get("history", [])]
    calls = []
    diagnostic_messages = []
    class Diagnostics(logging.Handler):
        def emit(self, record):
            diagnostic_messages.append(record.getMessage())
    handler = Diagnostics()
    loop.logger.addHandler(handler)
    original_post = loop._post_llm
    def traced_post(url, **kwargs):
        item = {"elapsed_ms": None, "usage": None}
        calls.append(item)
        start = perf_counter()
        try:
            response = original_post(url, **kwargs)
            item["status_code"] = response.status_code
            item["usage"] = response.json().get("usage")
            return response
        finally:
            item["elapsed_ms"] = round((perf_counter()-start)*1000, 2)
    rain = {"rain": True, "peak": 80}
    started = perf_counter()
    row = {"id": case["id"], "category": case["category"]}
    llm_circuit_breaker.reset()
    try:
        with patch.object(loop, "agent_config", return_value=config), \
             patch.object(loop, "_post_llm", side_effect=traced_post), \
             patch.object(skills, "day_rain", return_value=rain):
            result = loop.run(tools, case["question"], history)
        if result is None:
            row["error"] = "AgentReturnedNone"
        else:
            facts = result["tool_result"]["skills"]
            row.update(answer=result["answer"], tool_facts=facts,
                       tool_contract_pass=tool_contract(facts, case))
            row.update(grade(result["answer"], [], case))
    except Exception as error:
        row["error"] = type(error).__name__
    finally:
        loop.logger.removeHandler(handler)
        row["diagnostics"] = diagnostic_messages
        close_llm_client()
    row.update(elapsed_ms=round((perf_counter()-started)*1000, 2), llm_calls=len(calls),
               request_trace=calls, cost=None, first_token_ms=None)
    return row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/agent.json"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    cases = read_cases(args.cases)
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[:args.limit]
    if not args.live:
        print(f"Validated {len(cases)} Agent cases; no external calls. Use --live to execute.")
        return
    rows = []
    for case in cases:
        rows.append(evaluate_case(case))
        write_report(args.output, rows, {"live": True, "data": "synthetic timetable and fixed rain fixture",
            "scope": "Agent loop only; seeded history; channel delivery tested separately",
            "grading": "tool names/arguments and keyword facets; factual correctness requires human review",
            "cost": "null until provider prices are supplied", "first_token": "not applicable: nonstreaming"})
        print(case["id"], rows[-1].get("error", "completed"), flush=True)

if __name__ == "__main__":
    main()
