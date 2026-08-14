from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.parse import urlparse

import httpx

from .evaluation import _token_f1, evaluate_case


@dataclass(frozen=True)
class LiveRun:
    case: str
    repetition: int
    passed: bool
    score: float
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    response: str


def validate_provider_url(provider: str, base_url: str) -> None:
    parsed = urlparse(base_url)
    if provider == "ollama" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Ollama evaluation must use a loopback URL")
    if provider == "openrouter" and base_url.rstrip("/") != "https://openrouter.ai/api/v1":
        raise ValueError("OpenRouter evaluation must use https://openrouter.ai/api/v1")


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _stability(responses: list[str]) -> float:
    if len(responses) < 2:
        return 1.0
    pairs = [
        _token_f1(responses[left], responses[right])
        for left in range(len(responses))
        for right in range(left + 1, len(responses))
    ]
    return round(mean(pairs), 3)


def run_live_evaluation(
    dataset: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    repetitions: int = 1,
    timeout_seconds: float = 60,
    input_cost_per_million: float = 0,
    output_cost_per_million: float = 0,
    include_responses: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    runs: list[LiveRun] = []
    responses_by_case: dict[str, list[str]] = {}
    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_seconds, transport=transport) as client:
        for case in dataset["cases"]:
            case_responses: list[str] = []
            for repetition in range(1, repetitions + 1):
                messages = case.get("messages") or [{"role": "user", "content": str(case["prompt"])}]
                started = time.perf_counter()
                response = client.post("/chat/completions", json={"model": model, "messages": messages, "stream": False})
                latency_ms = round((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                payload = response.json()
                content = str(payload["choices"][0]["message"]["content"])
                usage = payload.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens", 0))
                completion_tokens = int(usage.get("completion_tokens", 0))
                estimated_cost = (
                    prompt_tokens * input_cost_per_million + completion_tokens * output_cost_per_million
                ) / 1_000_000
                result = evaluate_case({**case, "actual": content})
                runs.append(
                    LiveRun(
                        case=str(case["name"]),
                        repetition=repetition,
                        passed=result.passed,
                        score=result.score,
                        latency_ms=latency_ms,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        estimated_cost_usd=round(estimated_cost, 8),
                        response=content if include_responses else "[redacted]",
                    )
                )
                case_responses.append(content)
            responses_by_case[str(case["name"])] = case_responses

    latencies = [run.latency_ms for run in runs]
    return {
        "suite": str(dataset.get("suite", "live-llm-evaluation")),
        "model": model,
        "runs": len(runs),
        "pass_rate": round(sum(run.passed for run in runs) / len(runs), 3) if runs else 0.0,
        "mean_score": round(mean(run.score for run in runs), 3) if runs else 0.0,
        "latency_ms": {"median": round(median(latencies)) if latencies else 0, "p95": _percentile(latencies, 0.95)},
        "stability": {name: _stability(responses) for name, responses in responses_by_case.items()},
        "prompt_tokens": sum(run.prompt_tokens for run in runs),
        "completion_tokens": sum(run.completion_tokens for run in runs),
        "estimated_cost_usd": round(sum(run.estimated_cost_usd for run in runs), 8),
        "results": [asdict(run) for run in runs],
    }


def meets_thresholds(
    report: dict[str, Any],
    *,
    minimum_pass_rate: float,
    minimum_stability: float,
    maximum_p95_ms: int,
    maximum_cost_usd: float,
) -> bool:
    stability_values = list(report["stability"].values())
    observed_stability = min(stability_values) if stability_values else 0.0
    return (
        report["pass_rate"] >= minimum_pass_rate
        and observed_stability >= minimum_stability
        and report["latency_ms"]["p95"] <= maximum_p95_ms
        and report["estimated_cost_usd"] <= maximum_cost_usd
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a live Ollama or OpenRouter model")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--provider", choices=("ollama", "openrouter"), default="ollama")
    parser.add_argument("--base-url")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--input-cost-per-million", type=float, default=0)
    parser.add_argument("--output-cost-per-million", type=float, default=0)
    parser.add_argument("--minimum-pass-rate", type=float, default=0.8)
    parser.add_argument("--minimum-stability", type=float, default=0.3)
    parser.add_argument("--maximum-p95-ms", type=int, default=120000)
    parser.add_argument("--maximum-cost-usd", type=float, default=1.0)
    parser.add_argument("--include-responses", action="store_true", help="Store model text in the ignored local report")
    parser.add_argument("--output", type=Path, default=Path("test-results/live-llm-evaluation.json"))
    args = parser.parse_args()
    base_url = args.base_url or ("http://127.0.0.1:11434/v1" if args.provider == "ollama" else "https://openrouter.ai/api/v1")
    validate_provider_url(args.provider, base_url)
    api_key = os.environ.get(args.api_key_env) if args.provider == "openrouter" else None
    if args.provider == "openrouter" and not api_key:
        parser.error(f"{args.api_key_env} is not set")
    report = run_live_evaluation(
        json.loads(args.dataset.read_text(encoding="utf-8")),
        base_url=base_url,
        model=args.model,
        api_key=api_key,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
        include_responses=args.include_responses,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    passed = meets_thresholds(
        report,
        minimum_pass_rate=args.minimum_pass_rate,
        minimum_stability=args.minimum_stability,
        maximum_p95_ms=args.maximum_p95_ms,
        maximum_cost_usd=args.maximum_cost_usd,
    )
    raise SystemExit(0 if passed else 1)
