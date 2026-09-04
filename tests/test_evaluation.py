import json
import sys

import pytest

from local_agent_gateway.evaluation import (
    _token_f1,
    evaluate_case,
    evaluate_dataset,
    main,
)


@pytest.mark.llm_eval
def test_evaluation_passes_when_requirements_are_met() -> None:
    result = evaluate_case(
        {
            "name": "safe answer",
            "actual": "Use an Authorization Bearer header and do not log the token.",
            "reference": "Use an Authorization Bearer header and never log the token.",
            "required_terms": ["Authorization", "Bearer"],
            "forbidden_terms": ["secret-value"],
            "minimum_score": 0.7,
        }
    )
    assert result.passed
    assert result.score >= 0.7


@pytest.mark.llm_eval
def test_evaluation_reports_missing_and_forbidden_terms() -> None:
    result = evaluate_case(
        {
            "name": "unsafe answer",
            "actual": "The secret-value was copied.",
            "required_terms": ["Authorization"],
            "forbidden_terms": ["secret-value"],
        }
    )
    assert not result.passed
    assert result.missing_terms == ["Authorization"]
    assert result.forbidden_terms == ["secret-value"]


@pytest.mark.llm_eval
def test_dataset_summary() -> None:
    report = evaluate_dataset(
        {
            "suite": "example",
            "cases": [{"name": "one", "actual": "ok", "required_terms": ["ok"]}],
        }
    )
    assert report["pass_rate"] == 1.0
    assert report["passed"] == report["total"] == 1


@pytest.mark.llm_eval
def test_empty_token_similarity_cases() -> None:
    assert _token_f1("", "") == 1.0
    assert _token_f1("answer", "") == 0.0
    assert _token_f1("answer", "different") == 0.0


@pytest.mark.llm_eval
def test_empty_dataset_summary() -> None:
    report = evaluate_dataset({"cases": []})
    assert report["pass_rate"] == 0.0
    assert report["mean_score"] == 0.0


@pytest.mark.llm_eval
def test_cli_writes_reports_and_returns_success(tmp_path, monkeypatch) -> None:
    dataset = tmp_path / "dataset.json"
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    dataset.write_text(json.dumps({"suite": "cli", "cases": [{"name": "ok", "actual": "ok", "required_terms": ["ok"]}]}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["local-agent-eval", str(dataset), "--json-output", str(json_output), "--markdown-output", str(markdown_output)],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert json.loads(json_output.read_text())["pass_rate"] == 1.0
    assert "PASS" in markdown_output.read_text()
