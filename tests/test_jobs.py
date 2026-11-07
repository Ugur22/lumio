"""Replies run as jobs that outlive the request: disconnect, resume, cancel, images mid-stream, cleanup and trial refunds.

The routes are driven straight through the ASGI interface inside one event loop, because TestClient only returns once
the whole response is in and cannot drop a connection halfway.
"""

import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from conftest import ORIGIN, FakeStream
from test_generation import WAIT, image_files, leases, stored
from test_illustrate import PNG, PNG_BYTES, generator, new_chat, setup_profile

import server
import storage
from app import jobs, runtime, streaming

IMAGE_TEXT = "Once.\n\n[[image: a red barn at dawn]]\n\n"


class Paced(FakeStream):
    """Blocks before the pieces whose index has a gate, until the test opens it."""

    def __init__(self, pieces, gates=None, **kw):
        super().__init__(pieces, **kw)
        self.gates = gates or {}

    def __iter__(self):
        for i, chunk in enumerate(super().__iter__()):
            if gate := self.gates.get(i):
                assert gate.wait(WAIT), "test never opened the gate"
            yield chunk


@pytest.fixture(autouse=True)
def fresh_registry():
    jobs._jobs.clear()
    yield
    jobs._jobs.clear()


def serve(fake_client, pieces, gates=None, error=None):
    fake_client.chat.completions.create = lambda **_: Paced(pieces, gates, error=error)


async def asgi(method, path, body=None, headers=None, stop=None, seen=None):
    """One request through the app. `stop(text_so_far)` returning True drops the connection. Returns (status, body text)."""
    payload = json.dumps(body).encode() if body is not None else b""
    route, _, query = path.partition("?")
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": route, "raw_path": route.encode(), "query_string": query.encode(),
        "headers": [(b"host", b"localhost:8000"), (b"origin", ORIGIN.encode()), (b"content-type", b"application/json")]
        + [(k.lower().encode(), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1234), "server": ("localhost", 8000),
    }
    gone, sent = asyncio.Event(), False
    out = {"status": None, "body": ""}

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            if seen is not None:
                seen.update({k.decode().lower(): v.decode() for k, v in message["headers"]})
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"").decode()
            if stop and stop(out["body"]):
                gone.set()

    await server.app(scope, receive, send)
    return out["status"], out["body"]


def parse(text):
    """[(id, event name, data)] of an SSE body."""
    out = []
    for block in text.strip().split("\n\n") if text.strip() else []:
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return out


def names(text):
    return [name for _, name, _ in parse(text)]


async def job_ended(cid):
    job = jobs.find(cid, "local")
    await asyncio.wait({job.task}, timeout=WAIT)
    assert job.task.done()
    return job


def send_text(cid, content="hi", stop=None, seen=None, **extra):
    return asgi("POST", f"/api/chats/{cid}/messages", {"content": content, **extra}, stop=stop, seen=seen)


def after_image(text):
    return "event: image" in text


# --- the job outlives the connection ---


def test_every_event_has_a_running_id_from_zero(api, calls):
    cid = new_chat(api)

    status, body = asyncio.run(send_text(cid))

    assert status == 200
    evs = parse(body)
    assert [i for i, _, _ in evs] == list(range(len(evs)))
    assert evs[-1][1] == "done"


def test_a_disconnect_mid_stream_still_saves_the_full_reply_with_its_images(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)

    async def run():
        status, seen = await asgi("POST", f"/api/chats/{cid}/messages", {"content": "tell", "illustrate": True}, stop=after_image)
        assert "event: done" not in seen  # the client left while the model was still writing
        assert stored(cid) == []
        gate.set()
        await job_ended(cid)
        return seen

    seen = asyncio.run(run())

    chat = api.get(f"/api/chats/{cid}").json()
    (ref,) = chat["messages"][1]["images"]
    assert chat["messages"][1]["content"] == f"Once.\n\n[[img:{ref['id']}]]\n\nThen."
    assert "event: image" in seen
    assert leases() == 0 and len(image_files(cid)) == 1


def test_the_lease_follows_the_job_so_a_second_send_is_refused_until_it_ends(api, fake_client):
    gate = threading.Event()
    serve(fake_client, ["a", "b"], {1: gate})
    cid = new_chat(api)

    async def run():
        await send_text(cid, stop=lambda t: "event: delta" in t)
        assert leases() == 1  # the connection is gone, the lease is not
        busy, _ = await send_text(cid, "again")
        gate.set()
        await job_ended(cid)
        return busy

    assert asyncio.run(run()) == 409
    assert leases() == 0
    assert stored(cid) == ["hi", "ab"]


# --- resume ---


def test_resume_replays_after_last_event_id_then_follows_live(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)

    async def run():
        _, first = await asgi("POST", f"/api/chats/{cid}/messages", {"content": "x", "illustrate": True}, stop=after_image)
        last = parse(first)[-1][0]
        reader = asyncio.create_task(asgi("GET", f"/api/chats/{cid}/messages/stream", headers={"Last-Event-ID": str(last)}))
        await asyncio.sleep(0.2)
        assert not reader.done()  # nothing more to send yet: it is waiting on the model
        gate.set()
        status, rest = await asyncio.wait_for(reader, WAIT)
        _, whole = await asgi("GET", f"/api/chats/{cid}/messages/stream")
        return last, status, first, rest, whole

    last, status, first, rest, whole = asyncio.run(run())

    assert status == 200
    tail = parse(rest)
    assert [i for i, _, _ in tail] == list(range(last + 1, last + 1 + len(tail)))
    assert tail[-1][1] == "done" and "delta" in [n for _, n, _ in tail]
    assert [e for e in parse(first) + tail] == parse(whole)  # nothing lost, nothing repeated


def test_resume_works_after_completion_within_the_ttl_and_after_is_a_query_alternative(api, calls):
    cid = new_chat(api)

    async def run():
        _, live = await send_text(cid)
        return live, await asgi("GET", f"/api/chats/{cid}/messages/stream"), await asgi("GET", f"/api/chats/{cid}/messages/stream?after=1")

    live, (_, whole), (status, tail) = asyncio.run(run())

    assert status == 200 and parse(whole) == parse(live)
    assert parse(tail) == parse(live)[2:]


def test_the_last_event_id_header_wins_over_the_query(api, calls):
    cid = new_chat(api)

    async def run():
        _, live = await send_text(cid)
        return live, await asgi("GET", f"/api/chats/{cid}/messages/stream?after=0", headers={"Last-Event-ID": "2"})

    live, (_, tail) = asyncio.run(run())

    assert parse(tail) == parse(live)[3:]


def test_a_finished_job_is_forgotten_after_the_ttl(api, calls, monkeypatch):
    cid = new_chat(api)

    async def run():
        await send_text(cid)
        monkeypatch.setattr(jobs, "REPLAY_TTL", -1)
        return await asgi("GET", f"/api/chats/{cid}/messages/stream")

    status, body = asyncio.run(run())

    assert (status, body) == (204, "")
    assert jobs._jobs == {}


def test_resume_is_204_when_nothing_ran_and_404_for_an_unknown_chat(api):
    cid = new_chat(api)

    assert asyncio.run(asgi("GET", f"/api/chats/{cid}/messages/stream")) == (204, "")
    status, body = asyncio.run(asgi("GET", f"/api/chats/{'0' * 32}/messages/stream"))
    assert status == 404 and json.loads(body) == {"detail": "Chat not found"}
    assert asyncio.run(asgi("GET", f"/api/chats/{cid}/messages/stream?after=-2"))[0] == 422


def test_several_readers_of_one_job_all_get_the_whole_reply(api, fake_client):
    gate = threading.Event()
    serve(fake_client, ["a", "b", "c"], {1: gate})
    cid = new_chat(api)

    async def run():
        sender = asyncio.create_task(send_text(cid))
        await asyncio.sleep(0.2)
        readers = [asyncio.create_task(asgi("GET", f"/api/chats/{cid}/messages/stream")) for _ in range(3)]
        await asyncio.sleep(0.2)
        gate.set()
        return await asyncio.gather(sender, *readers)

    results = asyncio.run(run())

    bodies = [body for _, body in results]
    assert all(names(b)[-1] == "done" for b in bodies)
    assert len({json.dumps(parse(b)) for b in bodies}) == 1


# --- cancel ---


def test_cancel_saves_the_partial_reply_without_directives_or_images(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "more"], {1: gate})
    cid = new_chat(api)

    async def run():
        await asgi("POST", f"/api/chats/{cid}/messages", {"content": "x", "illustrate": True}, stop=after_image)
        assert (await asgi("POST", f"/api/chats/{cid}/messages/cancel"))[0] == 204
        job = await job_ended(cid)
        gate.set()  # lets the blocked read thread finish
        return job

    job = asyncio.run(run())

    chat = api.get(f"/api/chats/{cid}").json()
    assert [m["content"].strip() for m in chat["messages"]] == ["x", "Once."]
    assert chat["messages"][1]["images"] == []
    assert image_files(cid) == [] and leases() == 0
    assert job.finished_at is not None


def test_cancel_is_idempotent_and_does_nothing_when_nothing_runs(api, calls):
    cid = new_chat(api)

    async def run():
        first = await asgi("POST", f"/api/chats/{cid}/messages/cancel")
        await send_text(cid)
        return first, await asgi("POST", f"/api/chats/{cid}/messages/cancel"), await asgi("POST", f"/api/chats/{cid}/messages/cancel")

    first, second, third = asyncio.run(run())

    assert first == second == third == (204, "")
    assert stored(cid) == ["hi", "".join(["Hi *waves* ", "[[key]]x[[/key]]"])]


def test_cancel_answers_404_for_an_unknown_chat(api):
    status, _ = asyncio.run(asgi("POST", f"/api/chats/{'0' * 32}/messages/cancel"))
    assert status == 404


def test_a_disconnect_alone_never_cancels(api, fake_client):
    gate = threading.Event()
    serve(fake_client, ["a", "b"], {1: gate})
    cid = new_chat(api)

    async def run():
        await send_text(cid, stop=lambda t: "event: delta" in t)
        await asyncio.sleep(0.2)
        job = jobs.find(cid, "local")
        running = job.running
        gate.set()
        await job_ended(cid)
        return running

    assert asyncio.run(run()) is True
    assert stored(cid) == ["hi", "ab"]


# --- images ---


def test_images_are_sent_while_the_text_is_still_streaming_and_before_done(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)
    at_image = {}

    def stop(text):
        if after_image(text) and not gate.is_set():
            at_image["done"] = "event: done" in text
            at_image["after"] = names(text)
            gate.set()
        return False

    _, body = asyncio.run(asgi("POST", f"/api/chats/{cid}/messages", {"content": "x", "illustrate": True}, stop=stop))

    assert at_image["done"] is False and at_image["after"][-1] == "image"  # held back by the model, not by the save
    (image,) = [d for _, n, d in parse(body) if n == "image"]
    assert set(image) == {"id", "media_type", "prompt"} and image["prompt"] == "a red barn at dawn"
    assert names(body).index("image") < names(body).index("done")


def test_directives_generate_in_parallel_and_respect_the_cap(api, fake_client):
    setup_profile(api)
    seen, both = [], threading.Barrier(2, timeout=WAIT)

    def generate(**kw):
        seen.append(kw["prompt"])
        if len(seen) <= 2:
            both.wait()  # only passes when two images are being generated at the same time
        return type("R", (), {"data": [type("D", (), {"b64_json": PNG})()]})()

    fake_client.images.generate = generate
    pieces = ["[[image: one]]\n\n[[image: two]]\n\n[[image: three]]\n\n[[image: four]]", " end"]
    serve(fake_client, pieces)
    cid = new_chat(api)

    _, body = asyncio.run(send_text(cid, illustrate=True))

    assert names(body).count("image") == streaming.MAX_ILLUSTRATIONS and len(seen) == streaming.MAX_ILLUSTRATIONS
    saved = api.get(f"/api/chats/{cid}").json()["messages"][1]["content"]
    assert saved.count("[[img:") == 3 and "[[image" not in saved and saved.endswith("end")


def test_a_failed_illustration_is_reported_and_the_text_kept(api, fake_client):
    setup_profile(api)
    generator(fake_client, fail_on=("barn",))
    serve(fake_client, [IMAGE_TEXT, "Then."])
    cid = new_chat(api)

    _, body = asyncio.run(send_text(cid, illustrate=True))

    assert "illustration_failed" in names(body) and "image" not in names(body)
    assert names(body)[-1] == "done"
    assert stored(cid)[1] == "Once.\n\nThen."


def test_images_are_deleted_when_the_save_fails(api, fake_client, monkeypatch):
    setup_profile(api)
    generator(fake_client)
    serve(fake_client, [IMAGE_TEXT, "Then."])

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(storage.Store, "append_generated", locked)
    cid = new_chat(api)

    _, body = asyncio.run(send_text(cid, illustrate=True))

    assert "image" in names(body) and names(body)[-1] == "error"
    assert image_files(cid) == [] and stored(cid) == [] and leases() == 0


def test_images_are_deleted_when_the_model_fails_after_a_directive(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    serve(fake_client, [IMAGE_TEXT], error="connection lost")
    cid = new_chat(api)

    _, body = asyncio.run(send_text(cid, illustrate=True))

    assert names(body)[-1] == "error" and "done" not in names(body)
    assert image_files(cid) == [] and stored(cid) == [] and leases() == 0


# --- trial calls follow the job ---


def refunds_for(scenario):
    """Runs one job against a stub trial call and returns (refunds, saved texts)."""
    chat = runtime.db.create_chat(None, owner="local")
    lease = runtime.db.acquire(chat.id, owner="local")
    refunds = []
    call = SimpleNamespace(refund=lambda: refunds.append(1), remaining=3)
    gate = threading.Event()

    async def run():
        stream = Paced(["a", "b"], {1: gate} if scenario != "no text" else {0: gate})
        gen = streaming.stream_reply(chat, "q", stream, [], [], lease=lease, trial_call=call)
        job = jobs.start(chat.id, "local", gen)
        if scenario == "reader leaves":
            reader = job.follow(-1)
            await anext(reader)
            await reader.aclose()
            gate.set()
        elif scenario == "cancel after text":
            reader = job.follow(-1)
            await anext(reader)
            job.cancel()
        else:
            await asyncio.sleep(0.1)  # still waiting on the very first chunk
            job.cancel()
        await asyncio.wait({job.task}, timeout=WAIT)
        gate.set()

    asyncio.run(run())
    return refunds, [m.content for m in runtime.db.get_chat(chat.id, owner="local").messages]


def test_a_reader_leaving_neither_refunds_nor_stops_the_job():
    assert refunds_for("reader leaves") == ([], ["q", "ab"])


def test_cancel_after_text_keeps_the_call_spent_and_saves_the_partial():
    assert refunds_for("cancel after text") == ([], ["q", "a"])


def test_cancel_before_any_text_gives_the_call_back_once_and_saves_nothing():
    assert refunds_for("no text") == ([1], [])


# --- the buffer ---


def test_reasoning_stops_being_buffered_past_its_budget_but_everything_else_is_kept(monkeypatch):
    monkeypatch.setattr(jobs, "MAX_REASONING_BYTES", 1000)

    async def run():
        job = jobs.Job("c" * 32, "local")
        for _ in range(50):
            job.emit(streaming.sse("reasoning", {"text": "x" * 100}))
        job.emit(streaming.sse("delta", {"text": "kept"}))
        return job

    job = asyncio.run(run())

    assert sum(f.startswith("id:") and "event: reasoning" in f for f in job.frames) < 12
    assert job.frames[-1].startswith(f"id: {len(job.frames) - 1}\n") and "kept" in job.frames[-1]
    assert [int(f.split("\n", 1)[0][4:]) for f in job.frames] == list(range(len(job.frames)))


def test_a_job_that_crashes_ends_with_a_generic_error_and_frees_the_chat(api, fake_client):
    class Crashing(FakeStream):
        def __iter__(self):
            raise RuntimeError("secret internals")

    fake_client.chat.completions.create = lambda **_: Crashing([])
    cid = new_chat(api)

    status, body = asyncio.run(send_text(cid))

    assert status == 200 and names(body)[-1] == "error"
    assert "secret internals" not in body and leases() == 0


# --- review fixes ---


def test_a_request_cancelled_while_the_reply_is_prepared_still_hands_the_chat_to_a_job(api, fake_client):
    gate = threading.Event()

    def slow(**_):
        assert gate.wait(WAIT)
        return Paced(["ok"])

    fake_client.chat.completions.create = slow
    cid = new_chat(api)

    async def run():
        request = asyncio.create_task(send_text(cid))
        await asyncio.sleep(0.2)  # the worker thread is inside the model call
        request.cancel()
        gate.set()
        for _ in range(100):
            if jobs.find(cid, "local"):
                break
            await asyncio.sleep(0.05)
        await job_ended(cid)

    asyncio.run(run())

    assert stored(cid) == ["hi", "ok"] and leases() == 0


def test_every_job_has_an_id_sent_as_a_header_and_a_stale_cursor_gets_204(api, calls):
    cid = new_chat(api)

    async def run():
        first, resumed, wrong = {}, {}, {}
        await send_text(cid, seen=first)
        old = first["x-job-id"]
        same = await asgi("GET", f"/api/chats/{cid}/messages/stream?job={old}&after=0", seen=resumed)
        other = await asgi("GET", f"/api/chats/{cid}/messages/stream?job=nope", seen=wrong)
        second = {}
        await send_text(cid, "again", seen=second)
        stale = await asgi("GET", f"/api/chats/{cid}/messages/stream?job={old}")
        return old, same, resumed, other, second["x-job-id"], stale

    old, same, resumed, other, new, stale = asyncio.run(run())

    assert len(old) == 32 and new != old
    assert same[0] == 200 and resumed["x-job-id"] == old
    assert other == (204, "") and stale == (204, "")


@pytest.mark.parametrize("value", ["\u00b2", "abc", "1.5", "9" * 40, ""])
def test_a_malformed_last_event_id_is_a_422_not_a_500(api, calls, value):
    cid = new_chat(api)

    async def run():
        await send_text(cid)
        return await asgi("GET", f"/api/chats/{cid}/messages/stream", headers={"Last-Event-ID": value})

    assert asyncio.run(run())[0] == 422


def test_cancel_during_the_save_still_ends_the_stream_with_done(api, fake_client, monkeypatch):
    serve(fake_client, ["a"])
    saving, release = threading.Event(), threading.Event()
    real = storage.Store.append_generated

    def slow(self, *a, **k):
        saving.set()
        assert release.wait(WAIT)
        return real(self, *a, **k)

    monkeypatch.setattr(storage.Store, "append_generated", slow)
    cid = new_chat(api)

    async def run():
        reader = asyncio.create_task(send_text(cid))
        while not saving.is_set():
            await asyncio.sleep(0.02)
        assert (await asgi("POST", f"/api/chats/{cid}/messages/cancel"))[0] == 204
        release.set()
        return await asyncio.wait_for(reader, WAIT)

    _, body = asyncio.run(run())

    assert names(body)[-1] == "done"
    assert stored(cid) == ["hi", "a"] and leases() == 0


def test_cancel_before_any_text_ends_the_stream_with_an_error_frame(api, fake_client):
    gate = threading.Event()
    serve(fake_client, ["a"], {0: gate})
    cid = new_chat(api)

    async def run():
        reader = asyncio.create_task(send_text(cid))
        await asyncio.sleep(0.2)
        await asgi("POST", f"/api/chats/{cid}/messages/cancel")
        result = await asyncio.wait_for(reader, WAIT)
        gate.set()
        return result

    _, body = asyncio.run(run())

    assert names(body)[-1] == "error" and stored(cid) == [] and leases() == 0


def test_cancel_after_text_ends_the_stream_with_done_for_the_partial_reply(api, fake_client):
    gate = threading.Event()
    serve(fake_client, ["a", "b"], {1: gate})
    cid = new_chat(api)

    async def run():
        reader = asyncio.create_task(send_text(cid))
        await asyncio.sleep(0.2)
        await asgi("POST", f"/api/chats/{cid}/messages/cancel")
        result = await asyncio.wait_for(reader, WAIT)
        gate.set()
        return result

    _, body = asyncio.run(run())

    assert names(body)[-1] == "done" and stored(cid) == ["hi", "a"]


# --- fetching a picture before its turn is saved ---


def live_image(body):
    (image,) = [d for _, n, d in parse(body) if n == "image"]
    return image


def mid_job_image(cid, gate, fetch):
    """Runs a reply held at its second piece, and returns fetch(image) as run once the `image` event has arrived."""
    out = {}

    async def run():
        _, seen = await asgi("POST", f"/api/chats/{cid}/messages", {"content": "x", "illustrate": True}, stop=after_image)
        image = live_image(seen)
        assert "event: done" not in seen and stored(cid) == []
        out["result"] = await asyncio.to_thread(fetch, image)
        gate.set()
        await job_ended(cid)
        out["image"] = image

    asyncio.run(run())
    return out


def test_the_owner_can_fetch_a_picture_before_the_turn_is_saved(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)

    out = mid_job_image(cid, gate, lambda image: api.get(f"/api/chats/{cid}/images/{image['id']}"))

    res = out["result"]
    assert res.status_code == 200 and res.headers["content-type"] == "image/png" and res.content == PNG_BYTES
    assert res.headers["cache-control"].startswith("private")
    # once saved, the ordinary path serves the same picture
    again = api.get(f"/api/chats/{cid}/images/{out['image']['id']}")
    assert again.status_code == 200 and again.content == PNG_BYTES


def test_an_unknown_or_near_miss_id_is_still_404_mid_job(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)

    def fetch(image):
        flipped = ("0" if image["id"][0] != "0" else "1") + image["id"][1:]
        return [api.get(f"/api/chats/{cid}/images/{i}").status_code for i in ("f" * 32, flipped)]

    assert mid_job_image(cid, gate, fetch)["result"] == [404, 404]


def test_a_job_of_another_owner_does_not_serve_its_picture(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "Then."], {1: gate})
    cid = new_chat(api)

    def fetch(image):
        missing = api.get(f"/api/chats/{cid}/images/{'f' * 32}")
        job = jobs.find(cid, "local")
        job.owner = "someone-else"  # the chat is still the caller's, but the running job is not
        try:
            foreign = api.get(f"/api/chats/{cid}/images/{image['id']}")
        finally:
            job.owner = "local"
        return missing, foreign

    missing, foreign = mid_job_image(cid, gate, fetch)["result"]
    assert foreign.status_code == 404 and foreign.json() == missing.json()


def test_a_picture_of_a_failed_turn_is_not_served(api, fake_client, monkeypatch):
    setup_profile(api)
    generator(fake_client)
    serve(fake_client, [IMAGE_TEXT, "Then."])

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(storage.Store, "append_generated", locked)
    cid = new_chat(api)

    _, body = asyncio.run(send_text(cid, illustrate=True))

    image = live_image(body)
    assert image_files(cid) == []
    assert api.get(f"/api/chats/{cid}/images/{image['id']}").status_code == 404


def test_a_picture_of_a_cancelled_turn_is_not_served(api, fake_client):
    setup_profile(api)
    generator(fake_client)
    gate = threading.Event()
    serve(fake_client, [IMAGE_TEXT, "more"], {1: gate})
    cid = new_chat(api)

    async def run():
        _, seen = await asgi("POST", f"/api/chats/{cid}/messages", {"content": "x", "illustrate": True}, stop=after_image)
        await asgi("POST", f"/api/chats/{cid}/messages/cancel")
        await job_ended(cid)
        gate.set()
        return live_image(seen)

    image = asyncio.run(run())

    assert api.get(f"/api/chats/{cid}").json()["messages"][1]["images"] == []
    assert api.get(f"/api/chats/{cid}/images/{image['id']}").status_code == 404
