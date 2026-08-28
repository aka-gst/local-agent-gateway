"""Aggregate one test run into a machine-readable quality report.

The report is published next to the Allure HTML report so that any consumer,
including a static portfolio page, can render the same numbers CI enforced
instead of copying them by hand.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any

SCHEMA = "aka-gst.qa-metrics/1"
HISTORY_SCHEMA = "aka-gst.qa-metrics-history/1"
HISTORY_LIMIT = 20
REPOSITORY_URL = "https://github.com/aka-gst/local-agent-gateway"
REPORT_URL = "https://aka-gst.github.io/local-agent-gateway/"

SUITE_ORDER = ("Gateway API", "LLM evaluation", "End-to-end")
PASSING_STATUSES = frozenset({"passed"})
FAILING_STATUSES = frozenset({"failed", "broken"})


def _load_json(path: Path | None) -> Any | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _feature(labels: list[dict[str, Any]]) -> str:
    for label in labels:
        if label.get("name") == "feature":
            return str(label.get("value", "Other"))
    return "Other"


def collect_tests(allure_results: Path) -> dict[str, Any] | None:
    """Summarise allure-pytest raw results into totals and per-feature suites."""
    files = sorted(allure_results.glob("*-result.json")) if allure_results.is_dir() else []
    if not files:
        return None
    counts: dict[str, int] = {"passed": 0, "failed": 0, "broken": 0, "skipped": 0, "unknown": 0}
    suites: dict[str, dict[str, int]] = {}
    starts: list[int] = []
    stops: list[int] = []
    for file in files:
        payload = _load_json(file)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        suite = suites.setdefault(_feature(payload.get("labels") or []), {"total": 0, "passed": 0, "failed": 0})
        suite["total"] += 1
        if status in PASSING_STATUSES:
            suite["passed"] += 1
        elif status in FAILING_STATUSES:
            suite["failed"] += 1
        if isinstance(payload.get("start"), int):
            starts.append(payload["start"])
        if isinstance(payload.get("stop"), int):
            stops.append(payload["stop"])
    total = sum(counts.values())
    if not total:
        return None
    ordered = sorted(suites.items(), key=lambda item: (SUITE_ORDER.index(item[0]) if item[0] in SUITE_ORDER else len(SUITE_ORDER), item[0]))
    return {
        "total": total,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "broken": counts["broken"],
        "skipped": counts["skipped"],
        "pass_rate": round(counts["passed"] / total, 3),
        "duration_ms": max(stops) - min(starts) if starts and stops else None,
        "suites": [{"name": name, **values} for name, values in ordered],
        "status": "passed" if counts["failed"] == counts["broken"] == 0 else "failed",
    }


def collect_coverage(coverage_report: Path, threshold: float) -> dict[str, Any] | None:
    payload = _load_json(coverage_report)
    totals = payload.get("totals") if isinstance(payload, dict) else None
    if not isinstance(totals, dict) or "percent_covered" not in totals:
        return None
    percent = round(float(totals["percent_covered"]), 2)
    return {
        "percent": percent,
        "threshold": threshold,
        "covered_lines": totals.get("covered_lines"),
        "total_lines": totals.get("num_statements"),
        "missing_lines": totals.get("missing_lines"),
        "status": "passed" if percent >= threshold else "failed",
    }


def collect_deterministic_evaluation(report_path: Path) -> dict[str, Any] | None:
    payload = _load_json(report_path)
    if not isinstance(payload, dict) or "pass_rate" not in payload:
        return None
    results = payload.get("results") or []
    return {
        "suite": payload.get("suite"),
        "cases": payload.get("total", len(results)),
        "passed": payload.get("passed"),
        "pass_rate": payload["pass_rate"],
        "mean_score": payload.get("mean_score"),
        "status": "passed" if payload["pass_rate"] >= 1.0 else "failed",
    }


def collect_live_benchmark(benchmark_path: Path) -> dict[str, Any] | None:
    payload = _load_json(benchmark_path)
    if not isinstance(payload, dict) or "latency_ms" not in payload:
        return None
    stability = payload.get("stability") or {}
    stability_values = [float(value) for value in stability.values()] if isinstance(stability, dict) else []
    passed = payload.get("passed")
    if passed is None and payload.get("runs") is not None and payload.get("pass_rate") is not None:
        passed = round(float(payload["runs"]) * float(payload["pass_rate"]))
    return {
        "source": payload.get("source", "recorded-local-run"),
        "recorded_at": payload.get("recorded_at"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "environment": payload.get("environment"),
        "profile": payload.get("profile"),
        "runs": payload.get("runs"),
        "passed": passed,
        "pass_rate": payload.get("pass_rate"),
        "mean_score": payload.get("mean_score"),
        "latency_ms": payload["latency_ms"],
        "stability": {"min": min(stability_values) if stability_values else None, "by_case": stability},
        "prompt_tokens": payload.get("prompt_tokens"),
        "completion_tokens": payload.get("completion_tokens"),
        "estimated_cost_usd": payload.get("estimated_cost_usd"),
        "notes": payload.get("notes"),
    }


def _headline(
    tests: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    live: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """The four numbers a landing page shows above the fold."""
    cards: list[dict[str, Any]] = []
    if tests:
        cards.append(
            {
                "key": "tests",
                "value": tests["total"],
                "display": str(tests["total"]),
                "unit": "count",
                "status": tests["status"],
                "label": {"en": "Automated tests", "ru": "Автотестов"},
                "note": {
                    "en": " · ".join(f"{suite['name']} {suite['total']}" for suite in tests["suites"]),
                    "ru": " · ".join(f"{suite['name']} {suite['total']}" for suite in tests["suites"]),
                },
            }
        )
    if coverage:
        cards.append(
            {
                "key": "coverage",
                "value": coverage["percent"],
                "display": f"{coverage['percent']:.0f}%",
                "unit": "percent",
                "status": coverage["status"],
                "label": {"en": "Code coverage", "ru": "Покрытие кода"},
                "note": {
                    "en": f"CI threshold {coverage['threshold']:.0f}%",
                    "ru": f"порог CI — {coverage['threshold']:.0f}%",
                },
            }
        )
    if tests:
        cards.append(
            {
                "key": "pass_rate",
                "value": tests["pass_rate"],
                "display": f"{tests['pass_rate']:.0%}",
                "unit": "ratio",
                "status": tests["status"],
                "label": {"en": "Pass rate", "ru": "Pass rate"},
                "note": {
                    "en": f"{tests['passed']} of {tests['total']} in the last run",
                    "ru": f"{tests['passed']} из {tests['total']} в последнем прогоне",
                },
            }
        )
    if live:
        cards.append(
            {
                "key": "median_latency",
                "value": live["latency_ms"].get("median"),
                "display": f"{live['latency_ms'].get('median')} ms",
                "unit": "milliseconds",
                "status": "passed",
                "label": {"en": "Median latency", "ru": "Median latency"},
                "note": {
                    "en": f"{live.get('model')} local run, p95 {live['latency_ms'].get('p95')} ms",
                    "ru": f"{live.get('model')}, локальный прогон, p95 — {live['latency_ms'].get('p95')} мс",
                },
            }
        )
    return cards


def _overall_status(sections: list[dict[str, Any] | None]) -> str:
    statuses = [section["status"] for section in sections if section and "status" in section]
    if not statuses:
        return "unknown"
    return "passed" if all(status == "passed" for status in statuses) else "failed"


def _project_version() -> str:
    try:
        return package_version("local-agent-gateway")
    except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
        return "0.0.0"


def build_report(
    *,
    tests: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    deterministic: dict[str, Any] | None,
    live: dict[str, Any] | None,
    generated_at: str,
    commit: str | None = None,
    branch: str | None = None,
    run_url: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "project": {
            "name": "local-agent-gateway",
            "version": _project_version(),
            "repository": REPOSITORY_URL,
            "report": REPORT_URL,
        },
        "commit": {
            "sha": commit,
            "short": commit[:7] if commit else None,
            "branch": branch,
            "run_url": run_url,
        },
        "status": _overall_status([tests, coverage, deterministic]),
        "headline": _headline(tests, coverage, live),
        "tests": tests,
        "coverage": coverage,
        "evaluation": {"deterministic": deterministic, "live": live},
    }


def build_history(previous: Any, report: dict[str, Any], limit: int = HISTORY_LIMIT) -> dict[str, Any]:
    entries = previous.get("entries") if isinstance(previous, dict) else None
    entries = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    tests = report.get("tests") or {}
    coverage = report.get("coverage") or {}
    entry = {
        "generated_at": report["generated_at"],
        "commit": report["commit"].get("short"),
        "status": report["status"],
        "tests": tests.get("total"),
        "pass_rate": tests.get("pass_rate"),
        "coverage": coverage.get("percent"),
        "duration_ms": tests.get("duration_ms"),
    }
    entries = [existing for existing in entries if existing.get("generated_at") != entry["generated_at"]]
    entries.append(entry)
    return {"schema": HISTORY_SCHEMA, "entries": entries[-limit:]}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the published QA metrics report for one run")
    parser.add_argument("--allure-results", type=Path, default=Path("allure-results"))
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument("--coverage-threshold", type=float, default=90.0)
    parser.add_argument("--deterministic-eval", type=Path, default=Path("test-results/llm-evaluation.json"))
    parser.add_argument("--live-benchmark", type=Path, default=Path("evaluations/benchmarks/qwen3-8b.json"))
    parser.add_argument("--commit")
    parser.add_argument("--branch")
    parser.add_argument("--run-url")
    parser.add_argument("--previous-history", type=Path)
    parser.add_argument("--history-limit", type=int, default=HISTORY_LIMIT)
    parser.add_argument("--output", type=Path, default=Path("test-results/qa-metrics.json"))
    parser.add_argument("--history-output", type=Path, default=Path("test-results/qa-metrics-history.json"))
    args = parser.parse_args()

    report = build_report(
        tests=collect_tests(args.allure_results),
        coverage=collect_coverage(args.coverage, args.coverage_threshold),
        deterministic=collect_deterministic_evaluation(args.deterministic_eval),
        live=collect_live_benchmark(args.live_benchmark),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        commit=args.commit,
        branch=args.branch,
        run_url=args.run_url,
    )
    _write(args.output, report)
    _write(args.history_output, build_history(_load_json(args.previous_history), report, args.history_limit))
    print(json.dumps({key: report[key] for key in ("status", "headline")}, ensure_ascii=False, indent=2))
