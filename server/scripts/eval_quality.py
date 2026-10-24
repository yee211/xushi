"""Deterministic evaluation helpers; lexical checks are not a factual judge."""
import json
import math
import os
import re
from pathlib import Path
from statistics import fmean

PRICE_ENV_VARS = ("EVAL_PRICE_INPUT_PER_MTOK", "EVAL_PRICE_CACHED_PER_MTOK", "EVAL_PRICE_OUTPUT_PER_MTOK")


def prices_from_env():
    """读取模型单价（每百万 token，元）；输入/输出未配置时返回 None 表示不计成本。"""
    values = []
    for name in PRICE_ENV_VARS:
        raw = os.getenv(name, "").strip()
        if not raw:
            return None
        try:
            values.append(float(raw))
        except ValueError:
            return None
    return tuple(values)


def estimate_cost(usage_list, prices):
    """按 provider 返回的 usage 列表估算成本（元）：(输入-缓存)*输入价 + 缓存*缓存价 + 输出*输出价。"""
    if not prices:
        return None
    input_price, cached_price, output_price = prices
    total = 0.0
    for usage in usage_list:
        if not isinstance(usage, dict):
            continue
        prompt = float(usage.get("prompt_tokens") or 0)
        completion = float(usage.get("completion_tokens") or 0)
        cached = float((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        total += max(prompt - cached, 0) * input_price + cached * cached_price + completion * output_price
    return round(total / 1_000_000, 6)


def read_cases(path):
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [c["id"] for c in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("Cases must be nonempty with unique ids")
    return cases

def normalize(text):
    return re.sub(r"\s+", "", str(text)).lower()

def grade(answer, sources, case):
    text = normalize(answer)
    checks = case.get("checks", [])
    matched = [any(normalize(term) in text for term in alternatives) for alternatives in checks]
    expected = case.get("sources", [])
    source_hits = [any(str(s).replace("\\", "/").endswith(expected_source) for s in sources)
                   for expected_source in expected]
    numeric = [bool(re.search(r"(?<![\d.])" + re.escape(str(value)) + r"(?:\.0+)?(?![\d.])", answer.replace(",", "").replace("，", ""))) for value in case.get("numeric_values", [])]
    forbidden = case.get("forbidden", [])
    return {
        "facet_hits": matched,
        "numeric_value_presence": sum(numeric) / len(numeric) if numeric else None,
        "keyword_facet_coverage": sum(matched) / len(matched) if matched else None,
        "expected_source_coverage": sum(source_hits) / len(source_hits) if source_hits else None,
        "forbidden_hits": [term for term in forbidden if normalize(term) in text],
        "needs_human_review": True,
        "human_factual_correct": None,
        "human_source_consistent": None,
        "human_notes": "",
    }

def percentile(values, proportion):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * proportion) - 1)]

def summary(rows):
    completed = [r for r in rows if not r.get("error")]
    output = {"attempted": len(rows), "completed": len(completed), "failed": len(rows)-len(completed)}
    for key in ("elapsed_ms", "first_token_ms", "llm_calls", "keyword_facet_coverage",
                "expected_source_coverage", "tool_contract_pass", "numeric_value_presence"):
        values = [r[key] for r in completed if isinstance(r.get(key), int | float)]
        output[key + "_mean"] = round(fmean(values), 4) if values else None
    output["elapsed_ms_p95"] = percentile([r["elapsed_ms"] for r in completed if isinstance(r.get("elapsed_ms"), int | float)], .95)
    costs = [r["cost"] for r in completed if isinstance(r.get("cost"), int | float)]
    output["cost_total"] = round(sum(costs), 6) if costs else None
    return output

def write_report(path, rows, metadata):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"metadata": metadata, "summary": summary(rows), "cases": rows}
    modes = {r["mode"] for r in rows if "mode" in r}
    if modes:
        report["by_mode"] = {mode: summary([r for r in rows if r.get("mode") == mode]) for mode in sorted(modes)}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
