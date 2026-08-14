from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).parents[2]
TOKEN = "test-token-at-least-sixteen-characters"


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


@pytest.fixture(scope="session")
def gateway_url() -> Iterator[str]:
    upstream_port = _free_port()
    gateway_port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "GATEWAY_BEARER_TOKEN": TOKEN,
            "GATEWAY_ALLOWED_MODELS": "local-test-model",
            "GATEWAY_OLLAMA_BASE_URL": f"http://127.0.0.1:{upstream_port}/v1",
        }
    )
    upstream = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.fake_ollama:app", "--host", "127.0.0.1", "--port", str(upstream_port)],
        cwd=ROOT,
        env=environment,
        text=True,
    )
    gateway = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "local_agent_gateway.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(gateway_port)],
        cwd=ROOT,
        env=environment,
        text=True,
    )
    try:
        _wait_until_ready(f"http://127.0.0.1:{upstream_port}/docs", upstream)
        _wait_until_ready(f"http://127.0.0.1:{gateway_port}/health", gateway)
        yield f"http://127.0.0.1:{gateway_port}"
    finally:
        for process in (gateway, upstream):
            process.terminate()
        for process in (gateway, upstream):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.mark.e2e
def test_demo_success(page: Page, gateway_url: str) -> None:
    page.goto(f"{gateway_url}/demo")
    expect(page.locator("#health")).to_have_text("Gateway healthy")
    page.locator("#token").fill(TOKEN)
    page.locator("#send").click()
    expect(page.locator("#result")).to_have_text("gateway-ok")
    expect(page.locator("#request-id")).to_contain_text("Request ID:")


@pytest.mark.e2e
def test_demo_rejects_invalid_token(page: Page, gateway_url: str) -> None:
    page.goto(f"{gateway_url}/demo")
    page.locator("#token").fill("invalid-token")
    page.locator("#send").click()
    expect(page.locator("#result")).to_have_text("HTTP 401: unauthorized")
