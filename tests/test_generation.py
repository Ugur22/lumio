import asyncio
import base64
import gc
import json
import threading
from types import SimpleNamespace

import pytest
from conftest import ORIGIN, REPLY_PIECES, FakeStream
from fastapi.testclient import TestClient
from openai import OpenAIError

import server
import images
import storage
from app import runtime, streaming, routes_chats
from models import ImageData, NewMessage

WAIT = 10


class GatedStream(FakeStream):
    """Blocks before its first chunk until the test opens the gate, so a reply can be held in flight."""

    def __init__(self, pieces, started, gate, usage=None, **kw):
        super().__init__(pieces, **kw)
        self.started, self.gate, self.usage = started, gate, usage

    def __iter__(self):
        self.started.set()
        assert self.gate.wait(WAIT), "test never opened the gate"
        for chunk in super().__iter__():
            if self.usage:
                chunk.usage = SimpleNamespace(prompt_tokens=self.usage)
            yield chunk


@pytest.fixture
def held(fake_client):
    """The first model call returns a gated stream; later calls get a plain one."""
    state = SimpleNamespace(started=threading.Event(), gate=threading.Event(), usage=None, calls=0)

    def create(**kw):
        state.calls += 1
        if state.calls == 1:
            return GatedStream(REPLY_PIECES, state.started, state.gate, state.usage)
        return FakeStream(REPLY_PIECES)

    fake_client.chat.completions.create = create
    yield state
    state.gate.set()


def client():
    return TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def new_chat(api):
    return api.post("/api/chats").json()["id"]


def send_in_background(cid, content="hello"):
    out = {}

    def run():
        out["res"] = client().post(f"/api/chats/{cid}/messages", json={"content": content})

    thread = threading.Thread(target=run)
    thread.start()
    return thread, out


def finish(held, thread):
    held.gate.set()
    thread.join(WAIT)
    assert not thread.is_alive()


def leases():
    with runtime.db._read() as conn:
        return conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]


def event_names(res):
    return [block.split("\n")[0].removeprefix("event: ") for block in res.text.strip().split("\n\n")]


# --- simultaneous sends -------------------------------------------------------------------------


def test_second_send_to_a_busy_chat_is_rejected_and_the_first_still_completes(api, held):
    cid = new_chat(api)
    thread, out = send_in_background(cid)
    assert held.started.wait(WAIT)

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "me too"})

    assert res.status_code == 409
    assert "already being generated" in res.json()["detail"]
    finish(held, thread)
    assert out["res"].status_code == 200
    assert [m["content"] for m in api.get(f"/api/chats/{cid}").json()["messages"]][0] == "hello"
    assert len(api.get(f"/api/chats/{cid}").json()["messages"]) == 2
    assert leases() == 0


def test_other_chats_generate_while_one_is_busy(api, held):
    busy, free = new_chat(api), new_chat(api)
    thread, _ = send_in_background(busy)
    assert held.started.wait(WAIT)

    res = api.post(f"/api/chats/{free}/messages", json={"content": "independent"})

    assert res.status_code == 200 and event_names(res)[-1] == "done"
    finish(held, thread)


def test_the_chat_accepts_a_new_send_after_the_first_finished(api, held):
    cid = new_chat(api)
    thread, _ = send_in_background(cid)
    assert held.started.wait(WAIT)
    finish(held, thread)

    assert api.post(f"/api/chats/{cid}/messages", json={"content": "again"}).status_code == 200
    assert len(api.get(f"/api/chats/{cid}").json()["messages"]) == 4


# --- errors and cancellation release the lease --------------------------------------------------


def test_lease_is_released_when_the_model_call_fails(api, fake_client):
    def boom(**_):
        raise OpenAIError("down")

    fake_client.chat.completions.create = boom
    cid = new_chat(api)

    assert api.post(f"/api/chats/{cid}/messages", json={"content": "hi"}).status_code == 502
    assert leases() == 0


def test_lease_is_released_when_the_request_is_rejected(api, calls):
    cid = new_chat(api)

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi", "images": [{"media_type": "image/png", "data": "AAAA"}]})

    assert res.status_code == 422
    assert leases() == 0
    assert api.post(f"/api/chats/{cid}/messages", json={"content": "hi"}).status_code == 200


def test_lease_is_released_after_a_mid_stream_error(api, fake_client):
    fake_client.chat.completions.create = lambda **_: FakeStream(["partial"], error="lost")
    cid = new_chat(api)

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert event_names(res) == ["delta", "error"]
    assert leases() == 0


def test_stopping_keeps_the_partial_reply_and_releases_the_lease(api):
    cid = new_chat(api)
    lease = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)

    async def run():
        gen = streaming.stream_reply(chat, "Hello there", FakeStream(REPLY_PIECES), [], [], lease=lease)
        await anext(gen)
        await gen.aclose()

    asyncio.run(run())

    assert [m.content for m in routes_chats.load_chat(cid).messages] == ["Hello there", REPLY_PIECES[0]]
    assert leases() == 0


def test_cancelling_the_task_keeps_the_partial_reply_and_releases_the_lease(api):
    cid = new_chat(api)
    lease = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)

    async def run():
        seen = asyncio.Event()

        async def consume():
            async for _ in streaming.stream_reply(chat, "Hello there", FakeStream(REPLY_PIECES), [], [], lease=lease):
                seen.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(consume())
        await seen.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert [m.content for m in routes_chats.load_chat(cid).messages] == ["Hello there", REPLY_PIECES[0]]
    assert leases() == 0


def test_a_response_that_never_starts_does_not_keep_the_chat_locked(api, calls):
    cid = new_chat(api)

    response = routes_chats.send_message(cid, NewMessage(content="hi"))
    assert leases() == 1

    del response  # the client left before the first byte: the generator's own finally never runs
    gc.collect()

    assert leases() == 0


# --- deletion and settings changes during generation --------------------------------------------


def test_deleting_the_chat_mid_reply_does_not_bring_it_back(api, held):
    cid = new_chat(api)
    thread, out = send_in_background(cid)
    assert held.started.wait(WAIT)

    assert api.delete(f"/api/chats/{cid}").status_code == 204
    finish(held, thread)

    assert event_names(out["res"])[-1] == "error"
    assert "deleted" in out["res"].text
    assert api.get(f"/api/chats/{cid}").status_code == 404
    assert api.get("/api/chats").json() == []
    assert leases() == 0


def test_stopping_after_the_chat_was_deleted_does_not_bring_it_back(api):
    cid = new_chat(api)
    lease = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)

    async def run():
        gen = streaming.stream_reply(chat, "Hello", FakeStream(REPLY_PIECES), [], [], lease=lease)
        await anext(gen)
        runtime.db.delete_chat(cid)
        await gen.aclose()

    asyncio.run(run())

    assert runtime.db.chat_ids() == set()
    assert leases() == 0


def test_files_saved_for_a_reply_to_a_deleted_chat_are_removed(api):
    cid = new_chat(api)
    chat = routes_chats.load_chat(cid)
    lease = runtime.db.acquire(cid)
    runtime.db.delete_chat(cid)
    upload = ImageData(media_type="image/png", data=base64.b64encode(b"png-bytes").decode())

    with pytest.raises(storage.ChatNotFound):
        streaming.append_turn(chat, lease, "q", "a", [], [upload])
    lease.release()

    assert not (runtime.settings.images_dir / cid).exists()


def test_settings_changed_mid_reply_survive_and_the_stale_usage_is_dropped(api, held):
    held.usage = 1234
    cid = new_chat(api)
    thread, out = send_in_background(cid, "first message")
    assert held.started.wait(WAIT)

    assert api.put(f"/api/chats/{cid}/story", json={"bible": "new canon", "lore": []}).status_code == 200
    assert api.put(f"/api/chats/{cid}/behavior", json={"system_prompt": "be brief", "temperature": 0.3}).status_code == 200
    assert api.patch(f"/api/chats/{cid}", json={"title": "Renamed"}).status_code == 200
    finish(held, thread)

    chat = api.get(f"/api/chats/{cid}").json()
    assert (chat["bible"], chat["system_prompt"], chat["temperature"], chat["title"]) == ("new canon", "be brief", 0.3, "Renamed")
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["last_usage"] is None
    done = json.loads(out["res"].text.strip().split("\n\n")[-1].split("\n")[1].removeprefix("data: "))
    assert done["bible"] == "new canon"


def test_usage_is_recorded_when_nothing_changed_mid_reply(api, held):
    held.usage = 1234
    cid = new_chat(api)
    thread, _ = send_in_background(cid)
    assert held.started.wait(WAIT)
    finish(held, thread)

    assert api.get(f"/api/chats/{cid}").json()["last_usage"] == {"prompt_tokens": 1234}


def test_a_failed_save_is_reported_and_releases_the_lease(api, calls, monkeypatch):
    import sqlite3

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(streaming, "append_turn", locked)
    cid = new_chat(api)

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert event_names(res)[-1] == "error" and "could not be saved" in res.text
    assert leases() == 0


# --- a generation that lost its lease -----------------------------------------------------------


PNG = ImageData(media_type="image/png", data=base64.b64encode(b"png-bytes").decode())


def expire(cid):
    """Makes the chat's lease row look abandoned, without waiting for the TTL."""
    with runtime.db._tx() as conn:
        conn.execute("UPDATE generations SET expires=0 WHERE chat_id=?", (cid,))


def image_files(cid):
    return list((runtime.settings.images_dir / cid).glob("*")) if (runtime.settings.images_dir / cid).exists() else []


def stored(cid):
    return [m.content for m in routes_chats.load_chat(cid).messages]


async def drain(gen):
    return [block async for block in gen]


def test_a_stale_completed_reply_is_rejected_and_the_replacement_saves(api, monkeypatch):
    cid = new_chat(api)
    stale = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)
    made = []

    async def illustrated(chat_id, text, *_):
        made.extend(images.save_images(runtime.settings, chat_id, [PNG]))
        return text, made, []

    monkeypatch.setattr(streaming, "illustrate_reply", illustrated)

    async def run():
        gen = streaming.stream_reply(chat, "stale", FakeStream(REPLY_PIECES), [], [], [PNG], illustrate=(None, "m", None), lease=stale)
        await anext(gen)
        expire(cid)
        fresh = runtime.db.acquire(cid)
        return fresh, [block async for block in gen]

    fresh, rest = asyncio.run(run())

    assert rest[-1].startswith("event: error") and "another request took over" in rest[-1]
    assert not any(b.startswith("event: done") for b in rest)
    assert stored(cid) == []
    assert image_files(cid) == []
    assert leases() == 1  # the replacement's lease survived the stale generation's cleanup

    asyncio.run(drain(streaming.stream_reply(routes_chats.load_chat(cid), "fresh", FakeStream(REPLY_PIECES), [], [], lease=fresh)))
    assert stored(cid) == ["fresh", "".join(REPLY_PIECES)]
    assert leases() == 0


def test_a_stale_partial_reply_is_dropped_without_a_retry(api, monkeypatch):
    cid = new_chat(api)
    stale = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)
    attempts = []
    real = storage.Store.append_generated
    monkeypatch.setattr(storage.Store, "append_generated", lambda self, *a, **k: attempts.append(1) or real(self, *a, **k))

    async def run():
        gen = streaming.stream_reply(chat, "stale", FakeStream(REPLY_PIECES), [], [], [PNG], lease=stale)
        await anext(gen)
        expire(cid)
        fresh = runtime.db.acquire(cid)
        await gen.aclose()
        return fresh

    fresh = asyncio.run(run())

    assert attempts == [1]
    assert stored(cid) == []
    assert image_files(cid) == []
    assert leases() == 1
    streaming.append_turn(routes_chats.load_chat(cid), fresh, "fresh", "ok", [])
    assert stored(cid) == ["fresh", "ok"]
    fresh.release()
    assert leases() == 0


def test_a_reply_whose_lease_expired_with_no_replacement_is_not_saved(api):
    cid = new_chat(api)
    stale = runtime.db.acquire(cid)
    chat = routes_chats.load_chat(cid)

    async def run():
        gen = streaming.stream_reply(chat, "late", FakeStream(REPLY_PIECES), [], [], [PNG], lease=stale)
        await anext(gen)
        expire(cid)
        return [block async for block in gen]

    rest = asyncio.run(run())

    assert rest[-1].startswith("event: error")
    assert stored(cid) == [] and image_files(cid) == []
    assert routes_chats.load_chat(cid).title == "New chat"


def test_the_app_saves_replies_only_through_the_lease_checked_append():
    from pathlib import Path

    for path in Path(streaming.__file__).parent.glob("*.py"):
        assert "append_messages" not in path.read_text(), path.name


# --- Stop followed by an immediate resend -------------------------------------------------------


@pytest.fixture(autouse=True)
def no_acquire_wait(monkeypatch):
    monkeypatch.setattr(runtime.db, "acquire_wait", 0)


def test_a_send_that_arrives_just_before_the_previous_reply_is_saved_waits_for_it(api, held, monkeypatch):
    monkeypatch.setattr(runtime.db, "acquire_wait", 5)
    cid = new_chat(api)
    first, _ = send_in_background(cid, "first")
    assert held.started.wait(WAIT)
    second, out = send_in_background(cid, "second")

    threading.Timer(0.3, held.gate.set).start()
    first.join(WAIT)
    second.join(WAIT)

    assert out["res"].status_code == 200
    assert [m["content"] for m in api.get(f"/api/chats/{cid}").json()["messages"]][::2] == ["first", "second"]


def test_a_send_still_gets_409_when_the_lease_outlasts_the_wait(api, held, monkeypatch):
    monkeypatch.setattr(runtime.db, "acquire_wait", 0.3)
    cid = new_chat(api)
    thread, _ = send_in_background(cid)
    assert held.started.wait(WAIT)

    assert api.post(f"/api/chats/{cid}/messages", json={"content": "late"}).status_code == 409
    finish(held, thread)
