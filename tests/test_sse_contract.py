import json

from conftest import FakeStream, REPLY_PIECES
from openai import OpenAIError
from test_api import new_chat
from test_illustrate import STORY, events, generator, post, reply_with, setup_profile

import web
from models import Chat, ContextInfo, ImageRef, Source, Usage


def stream(api, content="Hello there"):
    cid = api.post("/api/chats").json()["id"]
    res = api.post(f"/api/chats/{cid}/messages", json={"content": content})
    assert res.status_code == 200
    events = []
    for block in res.text.strip().split("\n\n"):
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
