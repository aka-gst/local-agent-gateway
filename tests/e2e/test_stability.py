from __future__ import annotations

import os
import signal
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
TOKEN = "test-token-at-least-sixteen-characters"
MODEL = "local-test-model"
REQUEST_COUNT = 12


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, process: subprocess.Popen[str]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"test server exited early with {process.returncode}")
        try:
            if httpx.get(url, timeout=0.2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"test server did not become ready: {url}")


def _start_gateway(port: int, environment: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "local_agent_gateway.main"],
        cwd=ROOT,
        env={**environment, "GATEWAY_PORT": str(port)},
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def local_stack() -> Iterator[tuple[str, str, subprocess.Popen[str], dict[str, str]]]:
    upstream_port = _free_port()
    gateway_port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "GATEWAY_BEARER_TOKEN": TOKEN,
            "GATEWAY_ALLOWED_MODELS": MODEL,
            "GATEWAY_OLLAMA_BASE_URL": f"http://127.0.0.1:{upstream_port}/v1",
        }
    )
    upstream = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.fake_stability_backend:app", "--host", "127.0.0.1", "--port", str(upstream_port)],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    gateway = _start_gateway(gateway_port, environment)
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    try:
        _wait_until_ready(f"http://127.0.0.1:{upstream_port}/stats", upstream)
        _wait_until_ready(f"{gateway_url}/ready", gateway)
        yield gateway_url, f"http://127.0.0.1:{upstream_port}", gateway, environment
    finally:
        for process in (gateway, upstream):
            if process.poll() is None:
                process.terminate()
        for process in (gateway, upstream):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.mark.e2e
def test_concurrent_requests_remain_isolated_and_gateway_recovers_after_stops(
    local_stack: tuple[str, str, subprocess.Popen[str], dict[str, str]],
) -> None:
    gateway_url, upstream_url, gateway, environment = local_stack

    def request_once(index: int) -> tuple[str, float]:
        request_id = f"concurrent-{index}"
        started = time.monotonic()
        response = httpx.post(
            f"{gateway_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}", "X-Request-ID": request_id},
            json={"model": MODEL, "messages": [{"role": "user", "content": request_id}]},
            timeout=3,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        assert response.status_code == 200
        assert response.headers["x-request-id"] == request_id
        assert response.json()["choices"][0]["message"]["content"] == request_id
        return request_id, elapsed_ms

    with ThreadPoolExecutor(max_workers=REQUEST_COUNT) as executor:
        results = list(executor.map(request_once, range(REQUEST_COUNT)))
    assert {request_id for request_id, _ in results} == {f"concurrent-{index}" for index in range(REQUEST_COUNT)}
    latencies = sorted(elapsed for _, elapsed in results)
    p50 = statistics.median(latencies)
    p95 = latencies[round((REQUEST_COUNT - 1) * 0.95)]
    assert httpx.get(f"{upstream_url}/stats", timeout=1).json() == {"calls": REQUEST_COUNT}

    gateway.send_signal(signal.SIGINT)
    gateway.wait(timeout=5)
    assert gateway.returncode == 0

    restart_started = time.monotonic()
    gateway_port = int(gateway_url.rsplit(":", 1)[1])
    restarted = _start_gateway(gateway_port, environment)
    _wait_until_ready(f"{gateway_url}/ready", restarted)
    graceful_recovery_ms = (time.monotonic() - restart_started) * 1000

    restarted.kill()
    restarted.wait(timeout=5)
    assert restarted.returncode != 0

    forced_restart_started = time.monotonic()
    recovered = _start_gateway(gateway_port, environment)
    try:
        _wait_until_ready(f"{gateway_url}/ready", recovered)
        forced_recovery_ms = (time.monotonic() - forced_restart_started) * 1000
        print(
            "STABILITY_METRICS "
            f"requests={REQUEST_COUNT} backend_calls={REQUEST_COUNT} successes={REQUEST_COUNT} errors=0 "
            f"p50_ms={p50:.1f} p95_ms={p95:.1f} "
            f"graceful_recovery_ms={graceful_recovery_ms:.1f} forced_recovery_ms={forced_recovery_ms:.1f}"
        )
    finally:
        if recovered.poll() is None:
            recovered.terminate()
            recovered.wait(timeout=5)
