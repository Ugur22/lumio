import asyncio
import json
from types import SimpleNamespace

import pytest
from conftest import FakeStream, REPLY_PIECES
from openai import OpenAIError
from test_api import new_chat
from test_illustrate import STORY, events, generator, post, reply_with, setup_profile

import web
from app import runtime, streaming
from models import Chat, ContextInfo, ImageRef, Source, Usage
from conftest import sse_blocks


def stream(api, content="Hello there"):
    cid = api.post("/api/chats").json()["id"]
    res = api.post(f"/api/chats/{cid}/messages", json={"content": content})
    assert res.status_code == 200
    events = []
    for block in sse_blocks(res.text):
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


# The SSE payloads are not in the OpenAPI schema, so the generated types do not cover them. The frontend reads them
# through `DoneChat` (a Chat plus usage and context) and `{ text }` in types.ts and hooks/useChats.ts; these tests fail
# when the server emits something else, so a change here cannot slip past the frontend.


def test_delta_events_carry_only_text(api, calls):
    deltas = [data for name, data in stream(api) if name == "delta"]

    assert deltas == [{"text": piece} for piece in REPLY_PIECES]


def test_done_event_is_a_chat_plus_usage_and_context(api, calls):
    name, done = stream(api)[-1]

    assert name == "done"
    # Exactly the Chat fields (generated into api.gen.ts) plus the two extras DoneChat adds, no more and no fewer.
    assert set(done) == set(Chat.model_fields) | {"usage", "context"}
    Chat.model_validate({k: v for k, v in done.items() if k not in ("usage", "context")})
    ContextInfo.model_validate(done["context"])
    if done["usage"] is not None:
        Usage.model_validate(done["usage"])


# --- the other events ---
# Same reason: sources, image, illustration_failed and error are read by hand in api.ts (SourceRef, parseIllustrationFailure,
# errorMessage). Each assertion pins the exact key set the frontend relies on.


def test_sources_event_matches_what_the_frontend_reads(api, calls, monkeypatch):
    monkeypatch.setattr(web, "fetch_page", lambda url: Source(url=url, title="Page", text="body"))

    name, payload = stream(api, "summarise https://example.com/a")[0]

    assert name == "sources"
    assert set(payload) == {"sources", "notes", "query"}
    assert all(set(s) == {"url", "title"} for s in payload["sources"])
    assert isinstance(payload["notes"], list) and (payload["query"] is None or isinstance(payload["query"], str))


def test_image_event_is_an_image_ref(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, STORY)
    generator(fake_client)
    cid = new_chat(api)

    evs = events(post(api, cid, content="tell a story", illustrate=True))

    images = [d for n, d in evs if n == "image"]
    assert images
    for payload in images:
        assert set(payload) == set(ImageRef.model_fields)
        ImageRef.model_validate(payload)


def test_illustration_failed_event_has_prompt_status_and_detail(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: a red barn]]\n\nB")

    def generate(**kw):
        raise OpenAIError("no image today")

    fake_client.images.generate = generate
    cid = new_chat(api)

    evs = events(post(api, cid, content="x", illustrate=True))

    (payload,) = [d for n, d in evs if n == "illustration_failed"]
    assert set(payload) == {"prompt", "status", "detail"}
    assert isinstance(payload["prompt"], str) and isinstance(payload["detail"], str)
    assert payload["status"] is None or isinstance(payload["status"], int)


def test_error_event_carries_a_string_detail(api, fake_client):
    fake_client.chat.completions.create = lambda **_: FakeStream(["partial"], error="connection lost")

    name, payload = stream(api)[-1]

    assert name == "error"
    assert set(payload) == {"detail"} and isinstance(payload["detail"], str)


# --- reasoning ---
# Ephemeral: forwarded as `{ text }` while it streams, never part of the stored reply or of `done`.

REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")


class ThinkingStream(FakeStream):
    """Each piece is a dict of delta fields, so a test can send `content`, any reasoning field, or odd values."""

    def __iter__(self):
        for fields in self.pieces:
            delta = SimpleNamespace(**{"content": None, **fields})
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def think(fake_client, *chunks):
    fake_client.chat.completions.create = lambda **_: ThinkingStream(chunks)


@pytest.mark.parametrize("field", REASONING_FIELDS)
def test_reasoning_events_are_forwarded_in_order_with_only_text(api, fake_client, field):
    think(fake_client, {field: "Let me "}, {field: "think."}, {"content": "Hi "}, {"content": "there"})

    evs = stream(api)

    assert [(n, d) for n, d in evs if n in ("reasoning", "delta")] == [
        ("reasoning", {"text": "Let me "}),
        ("reasoning", {"text": "think."}),
        ("delta", {"text": "Hi "}),
        ("delta", {"text": "there"}),
    ]


def test_a_chunk_with_reasoning_and_content_emits_reasoning_first(api, fake_client):
    think(fake_client, {"reasoning": "hmm", "content": "Hi"})

    assert [e for e in stream(api) if e[0] != "done"] == [("reasoning", {"text": "hmm"}), ("delta", {"text": "Hi"})]


def test_reasoning_is_not_saved_and_not_in_done(api, fake_client):
    think(fake_client, {"reasoning_content": "secret musings"}, {"content": "The answer."})

    evs = stream(api)

    assert "secret musings" not in json.dumps(dict(evs)["done"])
    cid = dict(evs)["done"]["id"]
    stored = api.get(f"/api/chats/{cid}").json()
    assert "secret musings" not in json.dumps(stored)
    assert [m["content"] for m in stored["messages"]][-1] == "The answer."


@pytest.mark.parametrize("junk", [None, "", 5, True, ["x"], {"a": 1}])
def test_non_string_or_empty_reasoning_is_ignored(api, fake_client, junk):
    think(fake_client, {"reasoning_content": junk}, {"content": "Hi"})

    names = [n for n, _ in stream(api)]

    assert "reasoning" not in names and names.count("delta") == 1


def test_the_first_non_empty_string_field_wins(api, fake_client):
    think(fake_client, {"reasoning_content": "", "reasoning": 3, "thinking": "third"}, {"content": "Hi"})

    assert [d for n, d in stream(api) if n == "reasoning"] == [{"text": "third"}]


@pytest.mark.parametrize("field", REASONING_FIELDS)
def test_a_reasoning_only_stream_is_still_an_empty_reply_and_refunds(field):
    chat = runtime.db.create_chat(None, owner="local")
    lease = runtime.db.acquire(chat.id, owner="local")
    refunds = []
    call = SimpleNamespace(refund=lambda: refunds.append(1))

    async def run():
        source = ThinkingStream([{field: "hmm"}, {field: " more"}])
        return [e async for e in streaming.stream_reply(chat, "q", source, [], [], lease=lease, trial_call=call)]

    blocks = asyncio.run(run())

    assert [b.split("\n", 1)[0] for b in blocks] == ["event: reasoning", "event: reasoning", "event: error"]
    assert json.loads(blocks[-1].split("\n", 1)[1].removeprefix("data: ")) == {"detail": streaming.EMPTY_REPLY}
    assert refunds == [1]
    assert runtime.db.get_chat(chat.id, owner="local").messages == []
