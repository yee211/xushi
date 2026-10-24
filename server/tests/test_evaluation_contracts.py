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


def test_prices_from_env_requires_all_three_prices(monkeypatch):
    from scripts.eval_quality import prices_from_env
    for name in ("EVAL_PRICE_INPUT_PER_MTOK", "EVAL_PRICE_CACHED_PER_MTOK", "EVAL_PRICE_OUTPUT_PER_MTOK"):
        monkeypatch.delenv(name, raising=False)
    assert prices_from_env() is None
    monkeypatch.setenv("EVAL_PRICE_INPUT_PER_MTOK", "2")
    monkeypatch.setenv("EVAL_PRICE_CACHED_PER_MTOK", "0.4")
    assert prices_from_env() is None  # 缺输出价不计成本
    monkeypatch.setenv("EVAL_PRICE_OUTPUT_PER_MTOK", "8")
    assert prices_from_env() == (2.0, 0.4, 8.0)
    monkeypatch.setenv("EVAL_PRICE_INPUT_PER_MTOK", "free")
    assert prices_from_env() is None


def test_estimate_cost_splits_cached_and_uncached_tokens():
    from scripts.eval_quality import estimate_cost
    usage = {"prompt_tokens": 1000, "completion_tokens": 200,
             "prompt_tokens_details": {"cached_tokens": 400}}
    assert estimate_cost(None, None) is None
    assert estimate_cost([usage], None) is None
    # (1000-400)*2 + 400*0.4 + 200*8 = 2960 → 2960/1e6
    assert estimate_cost([usage], (2.0, 0.4, 8.0)) == 0.00296
    assert estimate_cost([usage, {"prompt_tokens": 100, "completion_tokens": 0}], (2.0, 0.4, 8.0)) == 0.00316
    assert estimate_cost([{"prompt_tokens": 50, "completion_tokens": 10}, None], (2.0, 0.4, 8.0)) == 0.00018


def test_summary_aggregates_case_costs_when_present():
    assert summary([{"cost": 0.002}, {"cost": 0.001}, {"error": "X"}])["cost_total"] == 0.003
    assert summary([{"cost": None}, {"error": "X"}])["cost_total"] is None


def test_identity_parameter_injection_fails_tool_contract():
    facts = [{"skill": "query_day_courses", "arguments": '{"date":"2026-09-09","user_id":2}'}]
    assert not tool_contract(facts, {"tool_sets": [["query_day_courses"]]})
