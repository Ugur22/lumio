"""Offline stand-in for an OpenAI-compatible provider.

Run standalone:  python -m tests.fake_upstream --port 9999   (then use http://127.0.0.1:9999/v1 as a base URL)
Or import `app` in pytest and drive it through a Starlette TestClient.

The scenario comes from the `X-Fake-Scenario` header, else from a `[[fake:NAME]]` marker in the last
user message (chat) or in the prompt (images). It needs no network and ignores the Authorization
header; nothing from a request body or header is ever logged.

Scenarios: plain (default), error (chat 500), illustrate (reply with an [[image: ...]] directive),
image-error (directive whose image call returns 500), code (reply with a runnable JavaScript block that
logs CODE_OUTPUT). The images endpoint always succeeds unless
the prompt contains FAILING_PROMPT or the header is `error`.
"""

import argparse
import base64
import json
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Smallest valid PNG header plus filler: the app only sniffs the magic bytes.
PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
PLAIN_PIECES = ["Hello ", "from the ", "fake upstream."]
ILLUSTRATE_PIECES = ["A barn at dawn.\n\n", "[[image: a red barn at dawn]]\n\n", "The end."]
FAILING_PROMPT = "fake-image-error"  # an image prompt containing this gets a 500
IMAGE_ERROR_PIECES = [f"A barn.\n\n[[image: {FAILING_PROMPT} barn]]\n\n", "The end."]
CODE_OUTPUT = "fake-code-output"
CODE_PIECES = ["Run this:\n\n", f"```js\nconsole.log(\"{CODE_OUTPUT}\");\n```\n"]
ERROR_BODY = {"error": {"message": "fake upstream failure", "type": "server_error"}}

_MARKER = re.compile(r"\[\[fake:([a-z-]+)\]\]")

app = FastAPI(title="fake-upstream")


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def _scenario(request: Request, text: str) -> str:
    header = request.headers.get("x-fake-scenario")
    if header:
        return header
    found = _MARKER.search(text)
    return found.group(1) if found else "plain"


def _chunk(delta: dict, finish: str | None = None) -> str:
    body = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 0, "model": "fake",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(body)}\n\n"


def _sse(pieces: list[str], usage: bool):
    yield _chunk({"role": "assistant", "content": ""})
    for piece in pieces:
        yield _chunk({"content": piece})
    yield _chunk({}, "stop")
    if usage:
        yield "data: " + json.dumps({"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 0, "model": "fake", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}) + "\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    users = [m for m in body.get("messages", []) if m.get("role") == "user"]
    scenario = _scenario(request, _text(users[-1].get("content")) if users else "")
    if scenario == "error":
        return JSONResponse(ERROR_BODY, status_code=500)
    pieces = {"illustrate": ILLUSTRATE_PIECES, "image-error": IMAGE_ERROR_PIECES, "code": CODE_PIECES}.get(scenario, PLAIN_PIECES)
    if not body.get("stream"):
        return {"id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": "fake",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(pieces)}, "finish_reason": "stop"}]}
    usage = bool((body.get("stream_options") or {}).get("include_usage"))
    return StreamingResponse(_sse(pieces, usage), media_type="text/event-stream")


@app.post("/v1/images/generations")
async def image_generations(request: Request):
    body = await request.json()
    if request.headers.get("x-fake-scenario") == "error" or FAILING_PROMPT in str(body.get("prompt", "")):
        return JSONResponse(ERROR_BODY, status_code=500)
    return {"created": int(time.time()), "data": [{"b64_json": PNG_B64}]}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "fake", "object": "model", "owned_by": "fake"}]}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
