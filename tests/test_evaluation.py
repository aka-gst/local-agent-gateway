import pytest

from local_agent_gateway.evaluation import evaluate_case, evaluate_dataset


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
