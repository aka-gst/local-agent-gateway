from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions() -> dict[str, object]:
    return {
        "id": "fake-completion",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "gateway-ok"}}],
    }
