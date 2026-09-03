from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from local_agent_gateway.app import create_app
from local_agent_gateway.config import Settings

TOKEN = "test-token-at-least-sixteen-characters"
MODEL = "local-test-model"
PROMPT = "synthetic-sensitive-prompt"
EXCEPTION_MESSAGE = "synthetic-sensitive-exception-message"
LOCAL_PATH = r"C:\synthetic-private\gateway\backend.py"
SENSITIVE_VALUES = (TOKEN, PROMPT, EXCEPTION_MESSAGE, LOCAL_PATH, "Traceback")
pytestmark = pytest.mark.api


def _test_settings() -> Settings:
    return Settings(
        bearer_token=TOKEN,
        allowed_backends="ollama",
        allowed_models=MODEL,
        ollama_base_url="http://127.0.0.1:11434/v1",
        upstream_timeout_seconds=1,
    )


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_safe_failure(response: httpx.Response, caplog, expected_status: int) -> None:
    assert response.status_code == expected_status
    assert response.headers["x-request-id"]
    captured = response.text + caplog.text
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in captured


def test_health_is_public_and_has_request_id() -> None:
    with TestClient(create_app(_test_settings())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_invalid_bearer_is_rejected_without_sensitive_output(caplog) -> None:
    caplog.set_level(logging.INFO, logger="local_agent_gateway")
    with TestClient(create_app(_test_settings())) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer synthetic-wrong-token"},
            json={"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]},
        )

    assert response.json()["error"]["message"] == "unauthorized"
    assert_safe_failure(response, caplog, 401)


def test_disallowed_backend_is_rejected_before_network_call(caplog) -> None:
    def unexpected_upstream(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network call must not occur")

    caplog.set_level(logging.INFO, logger="local_agent_gateway")
    app = create_app(_test_settings(), httpx.MockTransport(unexpected_upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={
                "backend": "synthetic-disallowed-backend",
                "model": MODEL,
                "messages": [{"role": "user", "content": PROMPT}],
            },
        )

    assert response.json()["error"]["message"] == "backend not allowed"
    assert_safe_failure(response, caplog, 400)


def test_disallowed_model_is_rejected_before_network_call(caplog) -> None:
    def unexpected_upstream(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network call must not occur")

    caplog.set_level(logging.INFO, logger="local_agent_gateway")
    app = create_app(_test_settings(), httpx.MockTransport(unexpected_upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={
                "model": "synthetic-disallowed-model",
                "messages": [{"role": "user", "content": PROMPT}],
            },
        )

    assert response.json()["error"]["message"] == "model not allowed"
    assert_safe_failure(response, caplog, 400)


def test_allowed_request_is_forwarded_without_client_auth_or_backend() -> None:
    captured: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["request_id"] = request.headers.get("x-request-id")
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "local", "choices": []})

    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={**auth(), "X-Request-ID": "test-request-1"},
            json={
                "backend": "ollama",
                "model": MODEL,
                "messages": [{"role": "user", "content": "secret prompt"}],
            },
        )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-1"
    assert captured == {
        "url": "http://127.0.0.1:11434/v1/chat/completions",
        "authorization": None,
        "request_id": "test-request-1",
        "json": {
            "model": MODEL,
            "messages": [{"role": "user", "content": "secret prompt"}],
        },
    }


def test_mlx_request_is_routed_to_the_mlx_loopback_upstream() -> None:
    captured: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "mlx-local", "choices": []})

    configured = Settings(
        bearer_token=TOKEN,
        allowed_backends="ollama,mlx",
        allowed_models=MODEL,
        ollama_base_url="http://127.0.0.1:11434/v1",
        mlx_base_url="http://127.0.0.1:8080/v1",
        upstream_timeout_seconds=1,
    )
    app = create_app(configured, httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={
                "backend": "mlx",
                "model": MODEL,
                "messages": [{"role": "user", "content": "synthetic prompt"}],
            },
        )

    assert response.status_code == 200
    assert captured == {
        "url": "http://127.0.0.1:8080/v1/chat/completions",
        "json": {
            "model": MODEL,
            "messages": [{"role": "user", "content": "synthetic prompt"}],
        },
    }


def test_streaming_request_is_forwarded_and_upstream_is_closed() -> None:
    captured: dict[str, object] = {}

    class SyntheticStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async def aclose(self) -> None:
            captured["closed"] = True

    def upstream(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["request_id"] = request.headers.get("x-request-id")
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=SyntheticStream(),
        )

    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={**auth(), "X-Request-ID": "stream-request-1"},
            json={
                "backend": "ollama",
                "model": MODEL,
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "stream-request-1"
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert captured == {
        "authorization": None,
        "request_id": "stream-request-1",
        "json": {
            "model": MODEL,
            "messages": [{"role": "user", "content": "synthetic prompt"}],
            "stream": True,
        },
        "closed": True,
    }


def test_upstream_connection_failure_is_neutral_and_safe(caplog) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"{EXCEPTION_MESSAGE} at {LOCAL_PATH}", request=request)

    caplog.set_level(logging.INFO, logger="local_agent_gateway")
    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]},
        )

    assert response.json()["error"]["message"] == "upstream unavailable"
    assert_safe_failure(response, caplog, 502)


def test_upstream_timeout_is_neutral_and_safe(caplog) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"{EXCEPTION_MESSAGE} at {LOCAL_PATH}")

    caplog.set_level(logging.INFO, logger="local_agent_gateway")
    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]},
        )

    assert response.json()["error"]["message"] == "upstream unavailable"
    assert_safe_failure(response, caplog, 502)


@pytest.mark.parametrize(
    ("headers", "content", "expected_status", "message"),
    [
        ({**auth(), "Content-Type": "text/plain"}, b"{}", 415, "unsupported media type"),
        ({**auth(), "Content-Type": "application/json"}, b"{", 400, "invalid request"),
        ({**auth(), "Content-Type": "application/json"}, b"[]", 400, "invalid request"),
        ({**auth(), "Content-Type": "application/json"}, b'{"model":"local-test-model"}', 400, "invalid request"),
    ],
)
def test_invalid_payloads_are_rejected(headers, content, expected_status, message) -> None:
    with TestClient(create_app(_test_settings())) as client:
        response = client.post("/v1/chat/completions", headers=headers, content=content)
    assert response.status_code == expected_status
    assert response.json()["error"]["message"] == message


def test_oversized_request_is_rejected_by_middleware() -> None:
    configured = _test_settings().model_copy(update={"max_request_bytes": 1024})
    with TestClient(create_app(configured)) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={**auth(), "Content-Type": "application/json"},
            content=b"x" * 1025,
        )
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "request too large"


def test_unsafe_request_id_is_replaced() -> None:
    with TestClient(create_app(_test_settings())) as client:
        response = client.get("/health", headers={"X-Request-ID": "unsafe id with spaces"})
    assert response.headers["x-request-id"] != "unsafe id with spaces"
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.parametrize("stream", [False, True])
def test_upstream_http_error_is_mapped_to_safe_502(stream: bool) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="synthetic private upstream details")

    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": MODEL, "messages": [], "stream": stream},
        )
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "upstream error"
    assert "private upstream" not in response.text


def test_invalid_upstream_json_is_mapped_to_safe_502() -> None:
    app = create_app(
        _test_settings(),
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": MODEL, "messages": []},
        )
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "invalid upstream response"


def test_streaming_connection_failure_is_safe() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic secret network path", request=request)

    app = create_app(_test_settings(), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": MODEL, "messages": [], "stream": True},
        )
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "upstream unavailable"
    assert "synthetic secret" not in response.text
