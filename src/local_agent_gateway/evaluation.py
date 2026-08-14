from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any


def _words(value: str) -> list[str]:
    return re.findall(r"[\w.-]+", value.casefold())


def _token_f1(actual: str, expected: str) -> float:
    actual_words = set(_words(actual))
    expected_words = set(_words(expected))
    if not actual_words or not expected_words:
        return float(actual_words == expected_words)
    overlap = len(actual_words & expected_words)
    precision = overlap / len(actual_words)
    recall = overlap / len(expected_words)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    passed: bool
    score: float
    missing_terms: list[str]
    forbidden_terms: list[str]


def evaluate_case(case: dict[str, Any]) -> EvaluationResult:
    actual = str(case["actual"])
    folded = actual.casefold()
    required = [str(term) for term in case.get("required_terms", [])]
    forbidden = [str(term) for term in case.get("forbidden_terms", [])]
    missing = [term for term in required if term.casefold() not in folded]
    present_forbidden = [term for term in forbidden if term.casefold() in folded]
    coverage = 1.0 if not required else (len(required) - len(missing)) / len(required)
    similarity = _token_f1(actual, str(case.get("reference", actual)))
    score = round(0.7 * coverage + 0.3 * similarity, 3)
    threshold = float(case.get("minimum_score", 0.7))
    return EvaluationResult(
        name=str(case["name"]),
        passed=not missing and not present_forbidden and score >= threshold,
        score=score,
        missing_terms=missing,
        forbidden_terms=present_forbidden,
    )


def evaluate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    results = [evaluate_case(case) for case in dataset["cases"]]
    return {
        "suite": str(dataset.get("suite", "llm-evaluation")),
        "passed": sum(result.passed for result in results),
        "total": len(results),
        "pass_rate": round(sum(result.passed for result in results) / len(results), 3) if results else 0.0,
        "mean_score": round(mean(result.score for result in results), 3) if results else 0.0,
        "results": [asdict(result) for result in results],
    }


def _markdown(report: dict[str, Any]) -> str:
    rows = ["# LLM evaluation report", "", f"Pass rate: **{report['pass_rate']:.0%}**", "", "| Case | Result | Score |", "|---|---:|---:|"]
    rows.extend(
        f"| {result['name']} | {'PASS' if result['passed'] else 'FAIL'} | {result['score']:.3f} |"
        for result in report["results"]
    )
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic LLM response evaluations")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("test-results/llm-evaluation.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("test-results/llm-evaluation.md"))
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    report = evaluate_dataset(json.loads(args.dataset.read_text(encoding="utf-8")))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report), end="")
    raise SystemExit(0 if report["pass_rate"] >= args.minimum_pass_rate else 1)
