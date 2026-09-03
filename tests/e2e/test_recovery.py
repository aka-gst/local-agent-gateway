from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
TOKEN = "test-token-at-least-sixteen-characters"


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_status(url: str, expected_status: int, process: subprocess.Popen[str]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"test server exited early with {process.returncode}")
        try:
            if httpx.get(url, timeout=0.2).status_code == expected_status:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"test server did not reach HTTP {expected_status}: {url}")


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@dataclass
class RecoveryHarness:
    upstream_port: int
    gateway_port: int
    environment: dict[str, str]
    upstream: subprocess.Popen[str]
    gateway: subprocess.Popen[str]

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.gateway_port}"

    @property
    def upstream_url(self) -> str:
        return f"http://127.0.0.1:{self.upstream_port}"

    def start_upstream(self) -> None:
        self.upstream = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.e2e.fake_ollama:app", "--host", "127.0.0.1", "--port", str(self.upstream_port)],
            cwd=ROOT,
            env=self.environment,
            text=True,
        )
        _wait_for_status(f"{self.upstream_url}/v1/models", 200, self.upstream)

    def start_gateway(self) -> None:
        self.gateway = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "local_agent_gateway.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(self.gateway_port)],
            cwd=ROOT,
            env=self.environment,
            text=True,
        )
        _wait_for_status(f"{self.gateway_url}/ready", 200, self.gateway)


@pytest.fixture
def recovery_harness() -> Iterator[RecoveryHarness]:
    environment = os.environ.copy()
    upstream_port = _free_port()
    gateway_port = _free_port()
    environment.update(
        {
            "GATEWAY_BEARER_TOKEN": TOKEN,
            "GATEWAY_ALLOWED_MODELS": "local-test-model",
            "GATEWAY_OLLAMA_BASE_URL": f"http://127.0.0.1:{upstream_port}/v1",
            "GATEWAY_UPSTREAM_TIMEOUT_SECONDS": "0.1",
        },
    )
    harness = RecoveryHarness(
        upstream_port=upstream_port,
        gateway_port=gateway_port,
        environment=environment,
        upstream=subprocess.Popen(["false"]),
        gateway=subprocess.Popen(["false"]),
    )
    harness.start_upstream()
    harness.start_gateway()
    try:
        yield harness
    finally:
        for process in (harness.gateway, harness.upstream):
            if process.poll() is None:
                _stop(process)


def _chat(url: str, content: str, *, stream: bool = False) -> httpx.Response:
    return httpx.post(
        f"{url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "model": "local-test-model",
            "messages": [{"role": "user", "content": content}],
            "stream": stream,
        },
        timeout=2,
    )


def _timed_chat(url: str) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    response = _chat(url, "parallel")
    return response, time.perf_counter() - started


@pytest.mark.e2e
def test_gateway_recovers_after_backend_and_gateway_restart(recovery_harness: RecoveryHarness) -> None:
    _stop(recovery_harness.upstream)
    not_ready = httpx.get(f"{recovery_harness.gateway_url}/ready", timeout=1)
    assert not_ready.status_code == 503
    assert not_ready.json()["error"]["message"] == "backend not ready"

    recovery_harness.start_upstream()
    _wait_for_status(f"{recovery_harness.gateway_url}/ready", 200, recovery_harness.gateway)

    _stop(recovery_harness.gateway)
    assert recovery_harness.gateway.poll() is not None
    recovery_harness.start_gateway()

    response = _chat(recovery_harness.gateway_url, "recovered")
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "gateway-ok"


@pytest.mark.e2e
def test_fault_harness_reports_timeout_drop_invalid_stream_and_concurrency(recovery_harness: RecoveryHarness) -> None:
    timeout = _chat(recovery_harness.gateway_url, "fault:timeout")
    assert timeout.status_code == 502
    assert timeout.json()["error"]["message"] == "upstream unavailable"

    invalid_stream = _chat(recovery_harness.gateway_url, "fault:invalid-stream", stream=True)
    assert invalid_stream.status_code == 502
    assert invalid_stream.json()["error"]["message"] == "invalid upstream stream"

    dropped_stream = _chat(recovery_harness.gateway_url, "fault:drop", stream=True)
    assert dropped_stream.status_code == 200
    assert b'"content":"partial"' in dropped_stream.content
    assert b"upstream stream interrupted" in dropped_stream.content
    assert dropped_stream.content.endswith(b"data: [DONE]\n\n")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: _timed_chat(recovery_harness.gateway_url), range(8)))
    responses = [response for response, _ in results]
    latencies = sorted(elapsed for _, elapsed in results)
    p50_ms = latencies[len(latencies) // 2] * 1000
    p95_ms = latencies[-1] * 1000
    assert all(response.status_code == 200 for response in responses)
    assert p95_ms < 1000

    metrics = httpx.get(f"{recovery_harness.upstream_url}/metrics", timeout=1).json()
    assert metrics == {"chat_calls": 11}
    print(f"recovery_harness p50_ms={p50_ms:.1f} p95_ms={p95_ms:.1f} backend_calls={metrics['chat_calls']}")
