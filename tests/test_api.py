import asyncio
import json

import pytest
from conftest import REPLY_PIECES, FakeStream
from openai import OpenAIError

import server


def new_chat(api):
    return api.post("/api/chats").json()["id"]


def send(api, cid, content):
    """Posts a message and returns the SSE events as (name, data) pairs."""
    res = api.post(f"/api/chats/{cid}/messages", json={"content": content})
    assert res.status_code == 200
    events = []
    for block in res.text.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_send_message_stores_turn_and_titles_chat(api, calls):
    cid = new_chat(api)
    events = send(api, cid, "Hello there")

    assert [name for name, _ in events] == ["delta", "delta", "done"]
    assert [d["text"] for name, d in events if name == "delta"] == REPLY_PIECES
    chat = events[-1][1]
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["content"] == "".join(REPLY_PIECES)
    assert chat["title"] == "Hello there"
    assert api.get(f"/api/chats/{cid}").json() == chat


def test_history_and_system_prompt_are_resent_each_turn(api, calls):
    cid = new_chat(api)
    send(api, cid, "one")
    send(api, cid, "two")

    assert [m["role"] for m in calls[1]] == ["system", "user", "assistant", "user"]
    assert calls[1][0]["content"] == server.SYSTEM_PROMPT


def test_system_prompt_is_never_stored(api, calls):
    cid = new_chat(api)
    send(api, cid, "hi")

    roles = {m["role"] for m in api.get(f"/api/chats/{cid}").json()["messages"]}
    assert roles == {"user", "assistant"}


def test_failed_model_call_saves_nothing(api, fake_client):
    def boom(**_):
        raise OpenAIError("upstream down")

    fake_client.chat.completions.create = boom
    cid = new_chat(api)

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert res.status_code == 502
    assert api.get(f"/api/chats/{cid}").json()["messages"] == []


def test_error_mid_stream_is_reported_and_saves_nothing(api, fake_client):
    fake_client.chat.completions.create = lambda **_: FakeStream(["partial"], error="connection lost")
    cid = new_chat(api)

    events = send(api, cid, "hi")

    assert [name for name, _ in events] == ["delta", "error"]
    assert events[-1][1]["detail"] == "connection lost"
    assert api.get(f"/api/chats/{cid}").json()["messages"] == []


def stop_after_first_delta(chat, content, stream):
    async def run():
        gen = server.stream_reply(chat, content, stream)
        await anext(gen)
        await gen.aclose()

    asyncio.run(run())


def test_stopped_stream_saves_the_partial_reply(api):
    chat = server.load_chat(new_chat(api))
    stream = FakeStream(REPLY_PIECES)

    stop_after_first_delta(chat, "Hello there", stream)

    saved = server.load_chat(chat.id)
    assert [m.content for m in saved.messages] == ["Hello there", REPLY_PIECES[0]]
    assert saved.title == "Hello there"
    assert stream.closed


def test_rename_list_and_delete(api, calls):
    cid = new_chat(api)
    send(api, cid, "hi")

    assert api.patch(f"/api/chats/{cid}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert api.get("/api/chats").json()[0]["message_count"] == 2
    assert api.delete(f"/api/chats/{cid}").status_code == 204
    assert api.get(f"/api/chats/{cid}").status_code == 404


@pytest.mark.parametrize("bad_id", ["g" * 32, "..%2F..%2Fetc%2Fpasswd", "abc"])
def test_malformed_chat_ids_are_rejected(api, bad_id):
    assert api.get(f"/api/chats/{bad_id}").status_code in (404, 422)


def test_empty_message_and_blank_title_are_rejected(api):
    cid = new_chat(api)

    assert api.post(f"/api/chats/{cid}/messages", json={"content": ""}).status_code == 422
    assert api.patch(f"/api/chats/{cid}", json={"title": ""}).status_code == 422


def test_corrupt_chat_file_is_skipped_in_list(api, calls):
    new_chat(api)
    (server.settings.data_dir / ("f" * 32 + ".json")).write_text("{not json")

    assert len(api.get("/api/chats").json()) == 1


def test_api_key_is_not_in_built_frontend():
    for f in server.FRONTEND_DIR.rglob("*"):
        if f.is_file():
            assert b"test-key" not in f.read_bytes(), f.name


@pytest.mark.skipif(not server.FRONTEND_DIR.exists(), reason="frontend not built")
def test_built_frontend_is_served(api):
    index = api.get("/")
    assert index.status_code == 200 and '<div id="root">' in index.text
