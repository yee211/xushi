"""Deterministic evaluation helpers; lexical checks are not a factual judge."""
import json
import math
import re
from pathlib import Path
from statistics import fmean


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
