from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from local_agent_gateway import qa_metrics
from local_agent_gateway.qa_metrics import (
    build_history,
    build_report,
    collect_coverage,
    collect_deterministic_evaluation,
    collect_live_benchmark,
    collect_tests,
)

pytestmark = pytest.mark.llm_eval


def _allure_result(name: str, status: str, feature: str, start: int, stop: int) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "start": start,
        "stop": stop,
        "labels": [{"name": "feature", "value": feature}],
    }


def _write_allure(directory: Path, results: list[dict[str, object]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index, result in enumerate(results):
        (directory / f"{index}-result.json").write_text(json.dumps(result), encoding="utf-8")
    (directory / "ignored-container.json").write_text("{}", encoding="utf-8")
    return directory


def test_tests_are_grouped_by_suite_in_report_order(tmp_path: Path) -> None:
    directory = _write_allure(
        tmp_path / "allure-results",
        [
            _allure_result("api", "passed", "Gateway API", 100, 200),
            _allure_result("eval", "passed", "LLM evaluation", 200, 300),
            _allure_result("browser", "passed", "End-to-end", 300, 900),
            _allure_result("extra", "skipped", "Other", 150, 160),
        ],
    )
    summary = collect_tests(directory)
    assert summary is not None
    assert summary["total"] == 4
    assert summary["passed"] == 3
    assert summary["skipped"] == 1
    assert summary["duration_ms"] == 800
    assert summary["status"] == "passed"
    assert [suite["name"] for suite in summary["suites"]] == ["Gateway API", "LLM evaluation", "End-to-end", "Other"]


def test_failed_and_broken_tests_fail_the_summary(tmp_path: Path) -> None:
    directory = _write_allure(
        tmp_path / "allure-results",
        [
            _allure_result("api", "failed", "Gateway API", 1, 2),
            _allure_result("broken", "broken", "Gateway API", 2, 3),
        ],
    )
    summary = collect_tests(directory)
    assert summary is not None
    assert summary["status"] == "failed"
    assert summary["failed"] == summary["broken"] == 1
    assert summary["pass_rate"] == 0.0
    assert summary["suites"][0]["failed"] == 2


def test_unreadable_and_missing_test_results_are_tolerated(tmp_path: Path) -> None:
    assert collect_tests(tmp_path / "missing") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert collect_tests(empty) is None
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "a-result.json").write_text("{ not json", encoding="utf-8")
    assert collect_tests(corrupt) is None


def test_result_without_feature_label_falls_back_to_other(tmp_path: Path) -> None:
    directory = tmp_path / "allure-results"
    directory.mkdir()
    (directory / "a-result.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    summary = collect_tests(directory)
    assert summary is not None
    assert summary["suites"] == [{"name": "Other", "total": 1, "passed": 1, "failed": 0}]
    assert summary["duration_ms"] is None


def test_coverage_is_compared_against_the_ci_threshold(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"totals": {"percent_covered": 99.135, "covered_lines": 458, "num_statements": 462, "missing_lines": 4}}),
        encoding="utf-8",
    )
    assert collect_coverage(report, 90.0) == {
        "percent": 99.14,
        "threshold": 90.0,
        "covered_lines": 458,
        "total_lines": 462,
        "missing_lines": 4,
        "status": "passed",
    }
    below = collect_coverage(report, 99.5)
    assert below is not None and below["status"] == "failed"


def test_missing_or_malformed_coverage_is_reported_as_absent(tmp_path: Path) -> None:
    assert collect_coverage(tmp_path / "missing.json", 90.0) is None
    malformed = tmp_path / "coverage.json"
    malformed.write_text(json.dumps({"totals": {}}), encoding="utf-8")
    assert collect_coverage(malformed, 90.0) is None


def test_deterministic_evaluation_requires_a_full_pass_rate(tmp_path: Path) -> None:
    report = tmp_path / "llm-evaluation.json"
    report.write_text(
        json.dumps({"suite": "s", "total": 3, "passed": 2, "pass_rate": 0.667, "mean_score": 0.8, "results": []}),
        encoding="utf-8",
    )
    summary = collect_deterministic_evaluation(report)
    assert summary is not None and summary["status"] == "failed"
    assert collect_deterministic_evaluation(tmp_path / "absent.json") is None


def test_live_benchmark_reports_its_recorded_origin_and_worst_stability() -> None:
    summary = collect_live_benchmark(Path("evaluations/benchmarks/qwen3-8b.json"))
    assert summary is not None
    assert summary["source"] == "recorded-local-run"
    assert summary["model"] == "qwen3:8b"
    assert summary["stability"]["min"] == 1.0
    assert summary["latency_ms"]["median"] < summary["latency_ms"]["p95"]


def test_live_benchmark_derives_the_passed_count_from_a_raw_runner_report(tmp_path: Path) -> None:
    raw = tmp_path / "live.json"
    raw.write_text(
        json.dumps({"runs": 9, "pass_rate": 1.0, "latency_ms": {"median": 10, "p95": 20}, "stability": {"case": 0.9}}),
        encoding="utf-8",
    )
    summary = collect_live_benchmark(raw)
    assert summary is not None
    assert summary["passed"] == 9
    assert summary["stability"]["min"] == 0.9
    assert summary["source"] == "recorded-local-run"


def test_live_benchmark_is_optional(tmp_path: Path) -> None:
    assert collect_live_benchmark(tmp_path / "absent.json") is None
    incomplete = tmp_path / "benchmark.json"
    incomplete.write_text(json.dumps({"model": "m"}), encoding="utf-8")
    assert collect_live_benchmark(incomplete) is None


def test_report_headline_exposes_the_four_landing_page_numbers() -> None:
    report = build_report(
        tests={
            "total": 50,
            "passed": 50,
            "failed": 0,
            "broken": 0,
            "skipped": 0,
            "pass_rate": 1.0,
            "duration_ms": 1600,
            "suites": [{"name": "Gateway API", "total": 50, "passed": 50, "failed": 0}],
            "status": "passed",
        },
        coverage={"percent": 99.0, "threshold": 90.0, "covered_lines": 1, "total_lines": 1, "missing_lines": 0, "status": "passed"},
        deterministic={"suite": "s", "cases": 3, "passed": 3, "pass_rate": 1.0, "mean_score": 0.86, "status": "passed"},
        live={"model": "qwen3:8b", "latency_ms": {"median": 3483, "p95": 14912}},
        generated_at="2026-08-28T00:00:00Z",
        commit="0123456789abcdef",
        branch="main",
        run_url="https://example.test/run/1",
    )
    assert report["schema"] == qa_metrics.SCHEMA
    assert report["status"] == "passed"
    assert report["commit"]["short"] == "0123456"
    assert [card["key"] for card in report["headline"]] == ["tests", "coverage", "pass_rate", "median_latency"]
    assert [card["display"] for card in report["headline"]] == ["50", "99%", "100%", "3483 ms"]
    assert all(set(card["label"]) == {"en", "ru"} for card in report["headline"])


def test_report_without_any_input_is_still_valid() -> None:
    report = build_report(
        tests=None,
        coverage=None,
        deterministic=None,
        live=None,
        generated_at="2026-08-28T00:00:00Z",
    )
    assert report["status"] == "unknown"
    assert report["headline"] == []
    assert report["commit"]["short"] is None
    assert report["project"]["version"]


def test_failing_section_fails_the_whole_report() -> None:
    report = build_report(
        tests={"total": 1, "passed": 0, "failed": 1, "broken": 0, "skipped": 0, "pass_rate": 0.0, "duration_ms": 1, "suites": [], "status": "failed"},
        coverage=None,
        deterministic=None,
        live=None,
        generated_at="2026-08-28T00:00:00Z",
    )
    assert report["status"] == "failed"


def test_history_appends_and_is_trimmed_to_the_limit() -> None:
    history: dict[str, object] = {"entries": ["not-a-dict"]}
    for index in range(5):
        report = build_report(
            tests={"total": 50, "passed": 50, "failed": 0, "broken": 0, "skipped": 0, "pass_rate": 1.0, "duration_ms": index, "suites": [], "status": "passed"},
            coverage={"percent": 99.0, "threshold": 90.0, "covered_lines": 1, "total_lines": 1, "missing_lines": 0, "status": "passed"},
            deterministic=None,
            live=None,
            generated_at=f"2026-08-2{index}T00:00:00Z",
            commit="abcdef1234",
        )
        history = build_history(history, report, limit=3)
    entries = history["entries"]
    assert isinstance(entries, list) and len(entries) == 3
    assert [entry["generated_at"] for entry in entries] == ["2026-08-22T00:00:00Z", "2026-08-23T00:00:00Z", "2026-08-24T00:00:00Z"]
    assert entries[-1] == {
        "generated_at": "2026-08-24T00:00:00Z",
        "commit": "abcdef1",
        "status": "passed",
        "tests": 50,
        "pass_rate": 1.0,
        "coverage": 99.0,
        "duration_ms": 4,
    }


def test_history_replaces_a_rerun_of_the_same_timestamp() -> None:
    report = build_report(
        tests=None, coverage=None, deterministic=None, live=None, generated_at="2026-08-28T00:00:00Z"
    )
    history = build_history(None, report)
    history = build_history(history, report)
    assert len(history["entries"]) == 1


def test_cli_writes_report_and_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    allure_dir = _write_allure(tmp_path / "allure-results", [_allure_result("api", "passed", "Gateway API", 1, 5)])
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": 99.0, "covered_lines": 99, "num_statements": 100, "missing_lines": 1}}), encoding="utf-8")
    output = tmp_path / "out" / "qa-metrics.json"
    history_output = tmp_path / "out" / "qa-metrics-history.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local-agent-qa-metrics",
            "--allure-results", str(allure_dir),
            "--coverage", str(coverage),
            "--deterministic-eval", str(tmp_path / "absent.json"),
            "--live-benchmark", str(tmp_path / "absent.json"),
            "--commit", "0123456789abcdef",
            "--branch", "main",
            "--run-url", "https://example.test/run/1",
            "--output", str(output),
            "--history-output", str(history_output),
        ],
    )
    qa_metrics.main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["evaluation"] == {"deterministic": None, "live": None}
    assert json.loads(history_output.read_text(encoding="utf-8"))["entries"][0]["commit"] == "0123456"
    assert "headline" in capsys.readouterr().out
