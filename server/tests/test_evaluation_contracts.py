"""Evaluation fixture and scorer regression; does not call providers."""
from pathlib import Path

from app.agent.skills import build_skills, dispatch
from scripts.eval_quality import grade, read_cases, summary
from scripts.evaluate_agent import fixture_tools, tool_contract


def test_agent_cases_cover_relevant_failure_and_history_scenarios():
    cases = read_cases(Path(__file__).resolve().parents[1] / "evals/agent_cases.jsonl")
    assert len(cases) >= 100
    assert {"history", "edge", "alias", "composite", "adversarial", "sync", "others",
            "availability", "weather", "chitchat"} <= {c["category"] for c in cases}
    for case in cases:
        assert case["question"]
        assert all(isinstance(c, list) and c for c in case["checks"])

def test_fixture_uses_real_query_logic_and_has_expected_times():
    skills = build_skills(fixture_tools())
    result = dispatch(skills, "query_day_courses", '{"date":"2026-09-09","period":"afternoon"}')
    assert [c["name"] for c in result["courses"]] == ["高等数学", "计算机组成原理"]
    assert result["courses"][0]["start_time"] == "14:00"
    result = dispatch(build_skills(fixture_tools("missing")), "query_day_courses", '{"date":"2026-09-09"}')
    assert result["error"] == "OUTSIDE_TERM"

def test_wrong_date_or_missing_tool_fails_contract():
    expected = {"tool_sets": [["query_day_courses", "get_weather"]],
                "arguments": [{"tool": "query_day_courses", "args": {"date": "2026-09-09"}}]}
    facts = [{"skill": "query_day_courses", "arguments": '{"date":"2026-09-08"}'}]
    assert not tool_contract(facts, expected)
    facts = [{"skill": "query_day_courses", "arguments": '{"date":"2026-09-09"}'},
             {"skill": "get_weather", "arguments": '{"date":"2026-09-09"}'}]
    assert tool_contract(facts, expected)

def test_keyword_hits_leave_fact_verdict_unreviewed():
    result = grade("高等数学在A101", [], {"checks": [["高等数学"], ["A101"]]})
    assert result["keyword_facet_coverage"] == 1
    assert result["human_factual_correct"] is None
    assert summary([{"error": "TimeoutError"}])["elapsed_ms_mean"] is None


def test_identity_parameter_injection_fails_tool_contract():
    facts = [{"skill": "query_day_courses", "arguments": '{"date":"2026-09-09","user_id":2}'}]
    assert not tool_contract(facts, {"tool_sets": [["query_day_courses"]]})
