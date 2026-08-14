import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    if payload.get("stream") is True:
        async def events() -> AsyncIterator[bytes]:
            for content in ("gateway-", "stream-ok"):
                chunk = {"choices": [{"delta": {"content": content}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")
    return {
        "id": "fake-completion",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "gateway-ok"}}],
    }
