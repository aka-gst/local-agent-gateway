from __future__ import annotations

import json
import sys

import httpx
import pytest

from local_agent_gateway import live_evaluation
from local_agent_gateway.live_evaluation import (
    meets_thresholds,
    run_live_evaluation,
    validate_provider_url,
)

pytestmark = pytest.mark.llm_eval


@pytest.mark.parametrize(
    ("provider", "url"),
    [
        ("ollama", "https://example.com/v1"),
        ("openrouter", "https://example.com/v1"),
    ],
)
def test_provider_url_restrictions(provider: str, url: str) -> None:
    with pytest.raises(ValueError):
        validate_provider_url(provider, url)


def test_supported_provider_urls() -> None:
    validate_provider_url("ollama", "http://127.0.0.1:11434/v1")
    validate_provider_url("openrouter", "https://openrouter.ai/api/v1")


def test_live_evaluation_collects_quality_latency_stability_tokens_and_cost() -> None:
    call_count = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.url.path.endswith("/chat/completions")
        request_body = json.loads(request.content)
        assert request_body["model"] == "test-model"
        assert request_body["max_tokens"] == 256
        assert request_body["temperature"] == 0.0
        assert request_body["seed"] == 42
        assert request_body["reasoning_effort"] == "none"
        content = "Use GET /health and expect status ok." if call_count == 1 else "Check GET /health; status should be ok."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    report = run_live_evaluation(
        {
            "suite": "live-test",
            "cases": [
                {
                    "name": "health",
                    "prompt": "How do I check health?",
                    "reference": "GET /health returns status ok",
                    "required_terms": ["/health", "status"],
                }
            ],
        },
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        repetitions=2,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
        transport=httpx.MockTransport(upstream),
    )
    assert report["runs"] == 2
    assert report["pass_rate"] == 1.0
    assert report["prompt_tokens"] == 20
    assert report["completion_tokens"] == 10
    assert report["estimated_cost_usd"] == pytest.approx(0.00004)
    assert 0 < report["stability"]["health"] <= 1
    assert all(result["response"] == "[redacted]" for result in report["results"])
    assert all(result["error"] is None for result in report["results"])


def test_empty_live_dataset_has_zero_metrics() -> None:
    report = run_live_evaluation(
        {"cases": []},
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: pytest.fail("network call was not expected")),
    )
    assert report["runs"] == 0
    assert report["pass_rate"] == 0.0
    assert report["latency_ms"] == {"median": 0, "p95": 0}


def test_quality_gates_check_pass_rate_stability_latency_and_cost() -> None:
    report = {
        "pass_rate": 1.0,
        "stability": {"case": 0.8},
        "latency_ms": {"p95": 500},
        "estimated_cost_usd": 0.01,
    }
    assert meets_thresholds(report, minimum_pass_rate=0.9, minimum_stability=0.7, maximum_p95_ms=1000, maximum_cost_usd=0.1)
    assert not meets_thresholds(report, minimum_pass_rate=0.9, minimum_stability=0.9, maximum_p95_ms=1000, maximum_cost_usd=0.1)
    assert not meets_thresholds(report, minimum_pass_rate=0.9, minimum_stability=0.7, maximum_p95_ms=100, maximum_cost_usd=0.1)
    assert not meets_thresholds(report, minimum_pass_rate=0.9, minimum_stability=0.7, maximum_p95_ms=1000, maximum_cost_usd=0.001)


def test_single_repetition_has_full_stability() -> None:
    response = {"choices": [{"message": {"content": "ok"}}]}
    report = run_live_evaluation(
        {"cases": [{"name": "one", "prompt": "answer", "required_terms": ["ok"]}]},
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)),
    )
    assert report["stability"] == {"one": 1.0}


def test_live_cli_writes_redacted_report(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = tmp_path / "dataset.json"
    output = tmp_path / "report.json"
    dataset.write_text(json.dumps({"cases": []}))
    fake_report = {
        "pass_rate": 1.0,
        "stability": {"case": 1.0},
        "latency_ms": {"p95": 1},
        "estimated_cost_usd": 0.0,
        "results": [{"response": "[redacted]"}],
    }
    monkeypatch.setattr(live_evaluation, "run_live_evaluation", lambda *args, **kwargs: fake_report)
    monkeypatch.setattr(sys, "argv", ["local-agent-live-eval", str(dataset), "--model", "test-model", "--output", str(output)])
    with pytest.raises(SystemExit) as exit_info:
        live_evaluation.main()
    assert exit_info.value.code == 0
    assert json.loads(output.read_text())["results"][0]["response"] == "[redacted]"


def test_openrouter_cli_requires_key(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"cases": []}))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["local-agent-live-eval", str(dataset), "--provider", "openrouter", "--model", "test/model"])
    with pytest.raises(SystemExit) as exit_info:
        live_evaluation.main()
    assert exit_info.value.code == 2


def test_transient_disconnect_is_retried() -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("synthetic disconnect", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    report = run_live_evaluation(
        {"cases": [{"name": "retry", "prompt": "answer", "required_terms": ["ok"]}]},
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        retries=1,
        transport=httpx.MockTransport(upstream),
    )
    assert calls == 2
    assert report["pass_rate"] == 1.0
    assert report["results"][0]["error"] is None


def test_persistent_disconnect_is_reported_without_crashing() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic private network details", request=request)

    report = run_live_evaluation(
        {"cases": [{"name": "failure", "prompt": "answer"}]},
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        retries=0,
        transport=httpx.MockTransport(upstream),
    )
    assert report["pass_rate"] == 0.0
    assert report["results"][0]["error"] == "upstream unavailable"
    assert "private" not in json.dumps(report)
