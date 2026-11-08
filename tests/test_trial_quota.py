# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: the call quota, refunds, the daily cap, and what a trial request asks of the model."""

import asyncio
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import FakeStream
from fake_upstream import app as upstream_app
from fastapi.testclient import TestClient
from openai import OpenAIError

import server
import storage
from app import providers, runtime, streaming
from models import Message, ProfileView
from trial_support import ENDED, ORIGIN, TRIAL_KEY, clean, events, idp, model, net, new_chat, send, session_of, trial_client, trial_on, trial_row


# --- quota ---------------------------------------------------------------------------------------------------------


def test_the_trial_profile_is_listed_as_managed_and_keyless(idp):
    client = trial_client(idp)

    res = client.get("/api/profiles")

    assert res.json()["active"] == "trial"
    (p,) = res.json()["profiles"]
    assert p | {"context_window": None} == {
        "id": "trial", "name": "Free trial", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "needs_key": True,
        "vision": False, "context_window": None, "image_model": None, "configured": True, "last4": None, "source": "server",
        "managed": True, "key_store": p["key_store"],
    }  # fmt: skip
    assert TRIAL_KEY not in res.text and not (TRIAL_KEY[-4:] in res.text)


def test_the_profile_model_has_the_managed_flag():
    assert ProfileView.model_fields["managed"].default is False
    assert "server" in json.dumps(ProfileView.model_json_schema())


def test_a_send_spends_one_call_and_reports_what_is_left(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    assert client.get(f"/api/chats/{chat_id}").json()["profile_id"] == "trial"

    evs = events(send(client, chat_id))

    assert evs[-1][0] == "done" and evs[-1][1]["trial"] == {"remaining": 4}
    assert client.get("/api/trial").json() == {"enrolled": True, "limit": 5, "used": 1, "remaining": 4, "ended": False}
    assert [m["role"] for m in client.get(f"/api/chats/{chat_id}").json()["messages"]] == ["user", "assistant"]


def test_the_sixth_send_is_a_402_and_the_profile_is_gone(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    for _ in range(5):
        assert send(client, chat_id).status_code == 200

    res = send(client, chat_id)

    assert res.status_code == 402 and res.json()["detail"] == ENDED
    assert len(model.calls) == 5
    assert client.get("/api/profiles").json() == {"active": None, "profiles": []}
    assert client.get("/api/trial").json() == {"enrolled": True, "limit": 5, "used": 5, "remaining": 0, "ended": True}


def test_twenty_parallel_sends_across_chats_get_exactly_five_replies(idp, model):
    client = trial_client(idp)
    token = session_of(client)
    chats = [new_chat(client) for _ in range(20)]
    barrier = threading.Barrier(20)

    def go(chat_id):
        c = TestClient(server.app, base_url=ORIGIN, headers={"Authorization": f"Bearer {token}"})
        barrier.wait()
        return c.post(f"/api/chats/{chat_id}/messages", json={"content": "hi"}).status_code

    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(go, chats))

    assert sorted(codes) == [200] * 5 + [402] * 15
    assert len(model.calls) == 5
    assert trial_row(client).used == 5


def test_a_refused_request_consumes_nothing(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    png = {"media_type": "image/png", "data": base64.b64encode(b"\x89PNG\r\n\x1a\nxx").decode()}

    assert send(client, chat_id, "x" * 4001).status_code == 422
    assert send(client, chat_id, "hi", web=True).status_code == 422
    assert send(client, chat_id, "hi", images=[png]).status_code == 422
    assert send(client, chat_id, "   ").status_code == 422

    assert trial_row(client).used == 0 and model.calls == []
    assert send(client, chat_id, "x" * 4000).status_code == 200  # the lease was released each time


def test_an_unreachable_provider_before_any_text_refunds_the_call(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    model.open_error = OpenAIError("upstream is down")

    res = send(client, chat_id)

    assert res.status_code == 502 and trial_row(client).used == 0
    assert client.get(f"/api/chats/{chat_id}").json()["messages"] == []


def test_a_stream_that_fails_before_any_text_refunds_the_call(idp, model):
    client = trial_client(idp)
    model.pieces, model.stream_error = [], "connection lost"

    evs = events(send(client, new_chat(client)))

    assert evs[-1][0] == "error" and trial_row(client).used == 0


def test_a_stream_that_fails_after_text_keeps_the_call_spent(idp, model):
    client = trial_client(idp)
    model.pieces, model.stream_error = ["part of a reply"], "connection lost"

    evs = events(send(client, new_chat(client)))

    assert [n for n, _ in evs] == ["delta", "error"] and trial_row(client).used == 1


def test_an_unexpected_error_before_the_reply_refunds_the_call(idp, model, monkeypatch):
    client = trial_client(idp)

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(providers, "open_stream", boom)
    with pytest.raises(RuntimeError):
        send(client, new_chat(client))

    assert trial_row(client).used == 0


def test_stopping_a_reply_does_not_refund_it(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat = runtime.db.create_chat("trial", owner=uid)
    lease = runtime.db.acquire(chat.id, owner=uid)
    call = runtime.db.reserve_trial_call(uid, 100)

    async def run():
        gen = streaming.stream_reply(chat, "q", FakeStream(["a", "b", "c"]), [], [], lease=lease, trial_call=call)
        first = await gen.__anext__()
        await gen.aclose()  # what a disconnect or Stop does
        return first

    assert "delta" in asyncio.run(run())
    assert runtime.db.get_trial(uid).used == 1


def test_a_refund_is_given_back_once(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    call = runtime.db.reserve_trial_call(uid, 100)
    other = runtime.db.reserve_trial_call(uid, 100)
    assert runtime.db.get_trial(uid).used == 2

    call.refund()
    call.refund()

    assert runtime.db.get_trial(uid).used == 1 and call.refunded and not other.refunded


def test_the_daily_cap_is_shared_and_a_refund_frees_a_slot(idp, model, monkeypatch):
    a, b = trial_client(idp, "alice"), trial_client(idp, "bob")
    monkeypatch.setattr(runtime.settings, "trial_daily_calls", 1)
    monkeypatch.setattr(runtime.settings, "trial_reserved_share", 0)
    model.open_error = OpenAIError("down")
    assert send(a, new_chat(a)).status_code == 502  # reserved, then refunded
    model.open_error = None

    assert send(a, new_chat(a)).status_code == 200
    full = send(b, new_chat(b))

    assert full.status_code == 503 and full.json()["detail"] == "Free trials are full today, try tomorrow"
    assert int(full.headers["retry-after"]) > 0
    assert trial_row(b).used == 0  # the refused send took nothing from bob either


def test_the_daily_cap_counts_per_utc_day(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    day1 = datetime(2030, 1, 1, 23, 59, tzinfo=timezone.utc)

    runtime.db.reserve_trial_call(uid, 1, now=day1)
    with pytest.raises(storage.TrialFull) as full:
        runtime.db.reserve_trial_call(uid, 1, now=day1)
    assert full.value.retry_after == 60
    runtime.db.reserve_trial_call(uid, 1, now=day1 + timedelta(minutes=2))  # past midnight UTC
    with runtime.db._read() as conn:
        assert [r["day"] for r in conn.execute("SELECT day FROM trial_usage")] == ["2030-01-02"]


def test_reserving_without_a_trial_is_refused(idp):
    with pytest.raises(storage.TrialExhausted):
        runtime.db.reserve_trial_call("nobody", 100)


def test_reasoning_only_tokens_count_as_delivered_and_are_not_refunded(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat = runtime.db.create_chat("trial", owner=uid)
    lease = runtime.db.acquire(chat.id, owner=uid)
    call = runtime.db.reserve_trial_call(uid, 100)

    class Thinking(FakeStream):
        def __iter__(self):
            delta = SimpleNamespace(content=None, reasoning_content="hmm")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
            raise OpenAIError("connection lost")

    async def run():
        return [e async for e in streaming.stream_reply(chat, "q", Thinking([]), [], [], lease=lease, trial_call=call)]

    asyncio.run(run())
    assert runtime.db.get_trial(uid).used == 1 and not call.refunded


# --- thinking off, and empty replies --------------------------------------------------------------------------


@pytest.fixture
def stub(monkeypatch):
    """The real SDK against the offline upstream stub, so the request body that would reach DeepSeek is what is asserted."""
    from fake_upstream import RECEIVED
    from openai import OpenAI

    sdk = OpenAI(base_url="https://fake-upstream.test/v1", api_key="k" * 20, http_client=TestClient(upstream_app), max_retries=0)
    monkeypatch.setattr(providers, "get_client", lambda profile, user: sdk)
    RECEIVED.clear()
    return RECEIVED


def saved_messages(client, chat_id):
    return client.get(f"/api/chats/{chat_id}").json()["messages"]


def test_the_trial_request_disables_thinking_and_keeps_the_clamps(idp, stub):
    client = trial_client(idp)
    chat_id = new_chat(client)
    client.patch(f"/api/chats/{chat_id}", json={"max_tokens": 9000, "temperature": 1.2})

    assert send(client, chat_id).status_code == 200

    body = stub[-1]
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == providers.TRIAL_MAX_TOKENS
    assert body["model"] == "deepseek-flash" and body["stream"] is True


def test_a_rejected_stream_options_retry_keeps_thinking_disabled(idp, fake_client):
    client = trial_client(idp)
    attempts = []

    class Rejected(OpenAIError):
        status_code = 400

    def create(model, messages, stream, **kw):
        attempts.append(kw)
        if "stream_options" in kw:
            raise Rejected("unknown parameter")
        return FakeStream(["ok"])

    fake_client.chat.completions.create = create
    assert send(client, new_chat(client)).status_code == 200

    assert len(attempts) == 2
    assert all(a["extra_body"] == {"thinking": {"type": "disabled"}} and a["max_tokens"] == providers.TRIAL_MAX_TOKENS for a in attempts)


def test_a_provider_that_rejects_the_thinking_field_fails_once_and_refunds(idp, fake_client):
    client = trial_client(idp)

    class Rejected(OpenAIError):
        status_code = 400

    def create(model, messages, stream, **kw):
        model_calls.append(kw)
        raise Rejected("unknown field thinking")

    model_calls = []
    fake_client.chat.completions.create = create

    res = send(client, new_chat(client))

    assert res.status_code == 502 and len(model_calls) == 2  # no loop, and the field was never dropped
    assert all("extra_body" in kw for kw in model_calls)
    assert trial_row(client).used == 0 and not providers._no_stream_options


def test_a_reasoning_only_stream_is_an_error_saves_nothing_and_refunds(idp, stub):
    client = trial_client(idp)
    chat_id = new_chat(client)

    evs = events(send(client, chat_id, "think hard [[fake:reasoning]]"))

    assert [n for n, _ in evs] == ["reasoning", "reasoning", "error"]
    assert evs[-1] == ("error", {"detail": "The model returned no answer. Try again or rephrase."})
    assert saved_messages(client, chat_id) == []
    assert trial_row(client).used == 0
    assert client.get("/api/trial").json()["remaining"] == 5
    assert send(client, chat_id, "again").status_code == 200  # the lease was released


def test_a_stream_with_no_content_at_all_is_also_refunded(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    model.pieces = ["", "  \n"]

    evs = events(send(client, chat_id))

    assert evs[-1][0] == "error" and evs[-1][1]["detail"].startswith("The model returned no answer")
    assert saved_messages(client, chat_id) == [] and trial_row(client).used == 0


def test_a_normal_stream_costs_exactly_one_call(idp, stub):
    client = trial_client(idp)
    chat_id = new_chat(client)

    evs = events(send(client, chat_id))

    assert evs[-1][0] == "done" and evs[-1][1]["trial"]["remaining"] == 4
    assert trial_row(client).used == 1 and len(saved_messages(client, chat_id)) == 2


def test_text_then_a_stream_error_is_not_refunded_and_saves_nothing_blank(idp, model):
    client = trial_client(idp)
    model.pieces, model.stream_error = ["some text"], "connection lost"

    evs = events(send(client, new_chat(client)))

    assert [n for n, _ in evs] == ["delta", "error"] and "no answer" not in evs[-1][1]["detail"]
    assert trial_row(client).used == 1


def test_trial_history_skips_blank_assistant_turns_with_their_question(idp, model):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat = runtime.db.create_chat("trial", owner=uid)

    for q, a in [("first", "answer one"), ("lost", "  \n"), ("third", "answer three")]:
        lease = runtime.db.acquire(chat.id, owner=uid)
        runtime.db.append_generated(lease, [Message(role="user", content=q), Message(role="assistant", content=a)], title="t")
        lease.release()

    assert send(client, chat.id, "now").status_code == 200

    sent = model.calls[-1]["messages"]
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "first"), ("assistant", "answer one"), ("user", "third"), ("assistant", "answer three"), ("user", "now"),
    ]
    assert model.calls[-1]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_a_history_that_starts_with_a_blank_reply_still_starts_with_a_user_message():
    history = [{"role": "assistant", "content": ""}, {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    assert providers.drop_blank_replies(history) == history[1:]
