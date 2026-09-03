from __future__ import annotations

import hmac
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
        raw_body = await request.body()
        if len(raw_body) > configured.max_request_bytes:
            return _error(413, "request too large", request_id)
        try:
            payload: Any = await request.json()
        except ValueError:
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
        base_url = configured.mlx_base_url if backend == "mlx" else configured.ollama_base_url
        upstream_url = f"{str(base_url).rstrip('/')}/chat/completions"
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

            async def forward_stream() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
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
