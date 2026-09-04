from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request

app = FastAPI()
calls = 0


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"data": [{"id": "local-test-model", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, object]:
    global calls
    calls += 1
    payload = await request.json()
    if payload.get("messages") == [{"role": "user", "content": "synthetic-slow"}]:
        await asyncio.sleep(0.25)
    request_id = request.headers["x-request-id"]
    return {
        "id": request_id,
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": request_id}}],
    }


@app.get("/stats")
async def stats() -> dict[str, int]:
    return {"calls": calls}
