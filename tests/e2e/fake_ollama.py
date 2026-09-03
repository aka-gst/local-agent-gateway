import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
chat_calls = 0


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"data": [{"id": "local-test-model", "object": "model"}]}


@app.get("/metrics")
async def metrics() -> dict[str, int]:
    return {"chat_calls": chat_calls}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    global chat_calls

    chat_calls += 1
    payload = await request.json()
    messages = payload.get("messages", [])
    content = messages[-1].get("content", "") if messages else ""
    if content == "fault:timeout":
        await asyncio.sleep(0.25)
    if payload.get("stream") is True:
        if content == "fault:invalid-stream":
            return JSONResponse({"error": "not an SSE response"})

        async def events() -> AsyncIterator[bytes]:
            if content == "fault:drop":
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                return
            for chunk_content in ("gateway-", "stream-ok"):
                chunk = {"choices": [{"delta": {"content": chunk_content}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")
    return {
        "id": "fake-completion",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "gateway-ok"}}],
    }
