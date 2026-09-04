from __future__ import annotations

import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .config import Settings, get_settings

logger = logging.getLogger("local_agent_gateway")
REQUEST_ID_HEADER = "X-Request-ID"
MAX_PENDING_SSE_EVENT_BYTES = 65_536
DEMO_HTML = Path(__file__).with_name("static").joinpath("index.html").read_text(encoding="utf-8")


def _safe_request_id(value: str | None) -> str:
    if value and len(value) <= 128 and all(character.isalnum() or character in "-_." for character in value):
        return value
    return uuid.uuid4().hex


def _error(status_code: int, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"message": message, "type": "gateway_error"},
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


def _backend_base_url(settings: Settings, backend: str) -> str:
    base_url = settings.mlx_base_url if backend == "mlx" else settings.ollama_base_url
    return str(base_url).rstrip("/")


async def _read_body_with_limit(request: Request, maximum_bytes: int) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum_bytes:
            return None
        body.extend(chunk)
    return bytes(body)


def _sse_event(event: bytes) -> tuple[bool, bool]:
    data_lines = [line[5:].lstrip() for line in event.replace(b"\r\n", b"\n").split(b"\n") if line.startswith(b"data:")]
    if len(data_lines) != 1:
        return False, False
    payload = data_lines[0]
    if payload == b"[DONE]":
        return True, True
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, False
    return isinstance(decoded, dict), False


def _stream_error(message: str, request_id: str) -> bytes:
    payload = json.dumps(
        {"error": {"message": message, "type": "gateway_error"}, "request_id": request_id},
        separators=(",", ":"),
    )
    return f"data: {payload}\n\ndata: [DONE]\n\n".encode()


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(configured.upstream_timeout_seconds),
        )
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(title="Local Agent Gateway", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _safe_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started = time.monotonic()
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > configured.max_request_bytes:
            response: Response = _error(413, "request too large", request_id)
        else:
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%d",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def readiness(request: Request) -> Response:
        request_id = request.state.request_id
        backend = configured.default_backend
        try:
            upstream = await request.app.state.http.get(f"{_backend_base_url(configured, backend)}/models")
        except httpx.TransportError:
            logger.warning("backend_not_ready request_id=%s backend=%s", request_id, backend)
            return _error(503, "backend not ready", request_id)
        if upstream.status_code >= 400:
            logger.warning(
                "backend_not_ready request_id=%s backend=%s status=%s",
                request_id,
                backend,
                upstream.status_code,
            )
            return _error(503, "backend not ready", request_id)
        return JSONResponse(
            content={"status": "ready", "backend": backend},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.get("/demo", response_class=HTMLResponse)
    async def demo() -> str:
        return DEMO_HTML

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        request_id = request.state.request_id
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not hmac.compare_digest(token, configured.bearer_token):
            return _error(401, "unauthorized", request_id)
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return _error(415, "unsupported media type", request_id)
        raw_body = await _read_body_with_limit(request, configured.max_request_bytes)
        if raw_body is None:
            return _error(413, "request too large", request_id)
        try:
            payload: Any = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error(400, "invalid request", request_id)
        if not isinstance(payload, dict):
            return _error(400, "invalid request", request_id)

        backend = payload.pop("backend", configured.default_backend)
        model = payload.get("model")
        if not isinstance(backend, str) or backend not in configured.backend_allowlist:
            return _error(400, "backend not allowed", request_id)
        if not isinstance(model, str) or model not in configured.model_allowlist:
            return _error(400, "model not allowed", request_id)
        if not isinstance(payload.get("messages"), list):
            return _error(400, "invalid request", request_id)
        upstream_url = f"{_backend_base_url(configured, backend)}/chat/completions"
        if payload.get("stream") is True:
            upstream_request = request.app.state.http.build_request(
                "POST",
                upstream_url,
                json=payload,
                headers={REQUEST_ID_HEADER: request_id},
            )
            try:
                upstream = await request.app.state.http.send(upstream_request, stream=True)
            except (httpx.TimeoutException, httpx.NetworkError):
                logger.warning("upstream_unavailable request_id=%s backend=%s", request_id, backend)
                return _error(502, "upstream unavailable", request_id)

            if upstream.status_code >= 400:
                await upstream.aclose()
                logger.warning(
                    "upstream_error request_id=%s backend=%s status=%s",
                    request_id,
                    backend,
                    upstream.status_code,
                )
                return _error(502, "upstream error", request_id)

            upstream_media_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if upstream_media_type != "text/event-stream":
                await upstream.aclose()
                logger.warning("invalid_upstream_stream request_id=%s backend=%s", request_id, backend)
                return _error(502, "invalid upstream stream", request_id)

            async def forward_stream() -> AsyncIterator[bytes]:
                pending = bytearray()
                completed = False
                try:
                    async for chunk in upstream.aiter_raw():
                        pending.extend(chunk)
                        while b"\n\n" in pending:
                            event, _, remainder = bytes(pending).partition(b"\n\n")
                            pending = bytearray(remainder)
                            valid, done = _sse_event(event)
                            if not valid:
                                logger.warning("invalid_upstream_stream request_id=%s backend=%s", request_id, backend)
                                yield _stream_error("invalid upstream stream", request_id)
                                return
                            yield event + b"\n\n"
                            completed = completed or done
                        if len(pending) > MAX_PENDING_SSE_EVENT_BYTES:
                            logger.warning("invalid_upstream_stream request_id=%s backend=%s", request_id, backend)
                            yield _stream_error("invalid upstream stream", request_id)
                            return
                    if pending or not completed:
                        logger.warning("upstream_stream_interrupted request_id=%s backend=%s", request_id, backend)
                        yield _stream_error("upstream stream interrupted", request_id)
                except httpx.TransportError:
                    logger.warning("upstream_stream_interrupted request_id=%s backend=%s", request_id, backend)
                    yield _stream_error("upstream stream interrupted", request_id)
                finally:
                    await upstream.aclose()

            return StreamingResponse(
                forward_stream(),
                media_type=upstream.headers.get("content-type"),
                headers={REQUEST_ID_HEADER: request_id},
            )

        try:
            upstream = await request.app.state.http.post(
                upstream_url,
                json=payload,
                headers={REQUEST_ID_HEADER: request_id},
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            logger.warning("upstream_unavailable request_id=%s backend=%s", request_id, backend)
            return _error(502, "upstream unavailable", request_id)

        if upstream.status_code >= 400:
            logger.warning(
                "upstream_error request_id=%s backend=%s status=%s",
                request_id,
                backend,
                upstream.status_code,
            )
            return _error(502, "upstream error", request_id)
        try:
            content = upstream.json()
        except ValueError:
            return _error(502, "invalid upstream response", request_id)
        return JSONResponse(content=content, headers={REQUEST_ID_HEADER: request_id})

    return app
