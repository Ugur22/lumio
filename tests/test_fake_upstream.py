"""End-to-end through the backend against the offline stub in fake_upstream.py (real OpenAI SDK, no sockets)."""

import json

import pytest
from fake_upstream import CODE_OUTPUT, FAILING_PROMPT, PLAIN_PIECES, app as upstream
from fastapi.testclient import TestClient
from openai import OpenAI
from app import providers


BASE = "https://fake-upstream.test/v1"


@pytest.fixture
def stub(monkeypatch):
    # TestClient is an httpx.Client, so the SDK talks to the stub in-process; no retries keeps 500s fast.
    sdk = OpenAI(base_url=BASE, api_key="k" * 20, http_client=TestClient(upstream), max_retries=0)
    monkeypatch.setattr(providers, "get_client", lambda profile, user: sdk)
    return sdk


@pytest.fixture
def chat_id(api, stub):
    body = {"name": "Fake", "base_url": BASE, "model": "fake", "key": "k" * 20, "image_model": "fake-img"}
    pid = api.post("/api/profiles", json=body).json()["profiles"][-1]["id"]
    api.post(f"/api/profiles/{pid}/activate")
    return api.post("/api/chats").json()["id"]


def post(api, cid, content, **extra):
    return api.post(f"/api/chats/{cid}/messages", json={"content": content, **extra})


def events(res):
    out = []
    for block in res.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_plain_stream_is_forwarded_and_stored(api, chat_id):
    res = post(api, chat_id, "hello")
    evs = events(res)

    assert [n for n, _ in evs if n == "delta"] and "".join(d["text"] for n, d in evs if n == "delta") == "".join(PLAIN_PIECES)
    assert evs[-1][0] == "done"
    assert evs[-1][1]["usage"] == {"prompt_tokens": 7}
    stored = api.get(f"/api/chats/{chat_id}").json()["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"] == "".join(PLAIN_PIECES)


def test_upstream_500_gives_502_and_saves_nothing(api, chat_id):
    res = post(api, chat_id, "boom [[fake:error]]")

    assert res.status_code == 502
    assert "fake upstream failure" in res.json()["detail"]
    assert api.get(f"/api/chats/{chat_id}").json()["messages"] == []


def test_illustrated_reply_stores_image(api, chat_id):
    evs = events(post(api, chat_id, "draw [[fake:illustrate]]", illustrate=True))

    names = [n for n, _ in evs]
    assert "image" in names and "illustration_failed" not in names and names[-1] == "done"
    reply = evs[-1][1]["messages"][-1]
    assert "[[image:" not in reply["content"] and "[[img:" in reply["content"]
    image = next(d for n, d in evs if n == "image")
    assert api.get(f"/api/chats/{chat_id}/images/{image['id']}").status_code == 200


def test_failed_illustration_is_reported_and_text_kept(api, chat_id):
    evs = events(post(api, chat_id, "draw [[fake:image-error]]", illustrate=True))

    failed = [d for n, d in evs if n == "illustration_failed"]
    assert len(failed) == 1 and failed[0]["status"] == 500 and FAILING_PROMPT in failed[0]["prompt"]
    assert "image" not in [n for n, _ in evs]
    assert evs[-1][0] == "done"
    assert "The end." in evs[-1][1]["messages"][-1]["content"]


def test_code_scenario_replies_with_a_fenced_js_block(api, chat_id):
    evs = events(post(api, chat_id, "show code [[fake:code]]"))

    text = "".join(d["text"] for n, d in evs if n == "delta")
    assert text.count("```") == 2 and "```js\n" in text and CODE_OUTPUT in text


def test_stub_never_needs_a_key():
    client = TestClient(upstream)
    res = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert res.status_code == 200 and res.text.rstrip().endswith("data: [DONE]")
    assert client.post("/v1/chat/completions", headers={"X-Fake-Scenario": "error"}, json={"messages": []}).status_code == 500
