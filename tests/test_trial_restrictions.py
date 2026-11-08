# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: what a trial account may not do, and the guarantee that the trial key never leaves the server."""

import json
import threading
from types import SimpleNamespace

from fake_upstream import app as upstream_app
from fastapi.testclient import TestClient
from openai import OpenAIError

import storage
from app import providers, routes_profiles, runtime, story
from models import UserView
from trial_support import ENDED, GITHUB_SECRET, GOOGLE_SECRET, PEPPER, TRIAL_KEY, browser, clean, idp, model, net, new_chat, send, sign_in, trial_client, trial_on, trial_row, use_up


# --- restrictions ----------------------------------------------------------------------------------------------------


def test_the_model_is_pinned_and_max_tokens_clamped_whatever_the_client_asks(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    assert client.put(f"/api/chats/{chat_id}/model", json={"model": "gpt-expensive", "context_window": 128000}).status_code == 200
    client.put(f"/api/chats/{chat_id}/behavior", json={"max_tokens": 900_000})
    send(client, chat_id)
    client.put(f"/api/chats/{chat_id}/behavior", json={"max_tokens": 100})
    send(client, chat_id)
    client.put(f"/api/chats/{chat_id}/behavior", json={})
    send(client, chat_id)

    assert {c["model"] for c in model.calls} == {"deepseek-flash"}
    assert [c["max_tokens"] for c in model.calls] == [1500, 100, 1500]


def test_illustrate_is_ignored_for_the_trial(idp, model):
    client = trial_client(idp)

    res = send(client, new_chat(client), illustrate=True)

    assert res.status_code == 200
    assert story.ILLUSTRATE_NOTE not in model.calls[0]["messages"][0]["content"]


def test_a_long_history_is_cut_to_twenty_messages_and_the_prompt_budget(idp, model):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat_id = new_chat(client)
    from models import Message

    runtime.db.append_messages(chat_id, [Message(role=("user" if i % 2 == 0 else "assistant"), content=f"{i}:" + "w" * 500) for i in range(60)], owner=uid)
    send(client, chat_id, "newest")

    sent = model.calls[0]["messages"]
    history = sent[1:-1]
    assert len(history) <= providers.TRIAL_HISTORY_MESSAGES and history[0]["role"] == "user"
    assert history[-1]["content"].startswith("59:") and sent[-1]["content"] == "newest"
    assert sum(len(m["content"]) for m in sent) <= providers.TRIAL_PROMPT_CHARS + 10


def test_a_prompt_over_the_budget_is_trimmed_oldest_first_and_refused_when_the_story_alone_is_too_big(idp, model, monkeypatch):
    client = trial_client(idp)
    chat_id = new_chat(client)
    send(client, chat_id, "first")
    monkeypatch.setattr(providers, "TRIAL_PROMPT_CHARS", 20_000)
    big = {"bible": "b" * 19_000, "lore": []}
    assert client.put(f"/api/chats/{chat_id}/story", json=big).status_code == 200

    res = send(client, chat_id, "x" * 3000)

    assert res.status_code == 422 and trial_row(client).used == 1


def test_summaries_are_blocked(idp, model):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    chat_id = new_chat(client)
    from models import Message

    runtime.db.append_messages(chat_id, [Message(role="user", content="m") for _ in range(12)], owner=uid)

    assert client.post(f"/api/chats/{chat_id}/summarize").status_code == 403


def test_at_most_fifty_chats(idp):
    client = trial_client(idp)
    for _ in range(providers.TRIAL_MAX_CHATS):
        new_chat(client)

    assert client.post("/api/chats").status_code == 403


def test_own_providers_unlock_only_after_the_trial(idp, model, monkeypatch):
    client = trial_client(idp)
    body = {"name": "Mine", "base_url": "https://api.example.com/v1", "model": "m", "key": "sk-mine-0123456789ab"}

    assert client.post("/api/profiles", json=body).json()["detail"] == "Adding your own provider unlocks when your free trial ends"
    assert client.post("/api/profiles/models", json={"base_url": "https://api.example.com/v1", "key": "k"}).status_code == 403
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 403
    assert client.delete("/api/web/key").status_code == 200  # removing is harmless

    use_up(client)

    class FakeSdk:
        def __init__(self, **kw):
            self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id="m1")])

        def close(self):
            pass

    monkeypatch.setattr(routes_profiles, "OpenAI", FakeSdk)
    assert client.post("/api/profiles", json=body).status_code == 201
    assert client.post("/api/profiles/models", json={"base_url": "https://api.example.com/v1", "key": "k"}).json() == {"models": ["m1"], "context_windows": None}
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 200


def test_a_trial_that_was_switched_off_unlocks_providers_and_hides_the_profile(idp, monkeypatch):
    client = trial_client(idp)
    monkeypatch.setattr(runtime.settings, "open_signup", False)

    assert client.get("/api/profiles").json()["profiles"] == []
    assert client.get("/api/trial").json()["ended"] is True
    assert client.put("/api/web/key", json={"key": "tvly-0123456789abcdef"}).status_code == 200


def test_a_chat_pinned_to_the_trial_falls_back_to_the_users_own_provider_afterwards(idp, model, monkeypatch):
    client = trial_client(idp)
    chat_id = new_chat(client)
    send(client, chat_id)
    use_up(client, 4)
    assert send(client, chat_id).status_code == 402 and ENDED in send(client, chat_id).text
    monkeypatch.setattr(routes_profiles, "OpenAI", lambda **kw: SimpleNamespace(close=lambda: None))
    client.post("/api/profiles", json={"name": "Mine", "base_url": "https://api.example.com/v1", "model": "my-model", "key": "sk-mine-0123456789ab"})

    res = send(client, chat_id)

    assert res.status_code == 200
    assert model.calls[-1]["model"] == "my-model"


def test_the_trial_cannot_be_forged_by_a_user_without_one(idp, model):
    client = trial_client(idp)
    stranger = browser()
    assert stranger.get("/api/trial").status_code == 401
    other, _ = sign_in(idp, "c-other", sub="sub-other", email="other@example.com")
    use_up(other)
    chat_id = new_chat(other)
    other.put(f"/api/chats/{chat_id}/behavior", json={"profile_id": "trial"})  # not in their store any more: 404

    assert other.put(f"/api/chats/{chat_id}/behavior", json={"profile_id": "trial"}).status_code == 404
    assert send(other, chat_id).status_code == 402
    assert client.get("/api/trial").json()["used"] == 0


def test_a_stored_profile_called_trial_gets_no_server_key(idp, monkeypatch):
    from models import Profile

    plain = Profile(id="trial", name="Mine", base_url="https://api.example.com/v1", model="m")

    assert not providers.is_trial(plain)
    assert providers.profile_key(plain, UserView(id="a" * 32, username="x", is_admin=False)) is None


# --- the key never leaves ----------------------------------------------------------------------------------------------


def test_the_client_talks_to_the_provider_with_the_trial_key_and_nothing_else_carries_it(idp, caplog, monkeypatch):
    import logging

    seen = []

    class Spy:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            body = []

            async def tap():
                message = await receive()
                body.append(message.get("body", b""))
                return message

            if scope["type"] == "http":
                seen.append({"auth": dict(scope["headers"]).get(b"authorization", b"").decode(), "body": body})
            await self.app(scope, tap, send)

    monkeypatch.setattr(runtime.settings, "trial_base_url", "https://fake-upstream.test/v1")
    monkeypatch.setattr(providers, "client_options", lambda: {"http_client": TestClient(Spy(upstream_app)), "max_retries": 0})
    caplog.set_level(logging.DEBUG, logger="dolphinllm")
    client = trial_client(idp)
    chat_id = new_chat(client)

    collected = [send(client, chat_id, "hello").text]
    collected += [send(client, chat_id, "boom [[fake:error]]").text]
    for path in ("/api/profiles", "/api/trial", "/api/auth/me", "/api/chats", f"/api/chats/{chat_id}", f"/api/chats/{chat_id}/context"):
        collected.append(client.get(path).text)
    collected.append(client.post("/api/profiles", json={"name": "x", "base_url": "https://a.example/v1", "model": "m"}).text)

    assert seen[0]["auth"] == f"Bearer {TRIAL_KEY}"
    sent = json.loads(b"".join(seen[0]["body"]))
    assert sent["model"] == "deepseek-flash" and sent["max_tokens"] == 1500
    blob = "\n".join(collected) + caplog.text
    for secret in (TRIAL_KEY, PEPPER, GOOGLE_SECRET, GITHUB_SECRET, "at-code-alice", "code-alice"):
        assert secret not in blob, secret


def test_error_text_from_the_provider_is_redacted(idp, model):
    client = trial_client(idp)
    chat_id = new_chat(client)
    model.open_error = OpenAIError(f"Incorrect API key provided: {TRIAL_KEY}")
    refused = send(client, chat_id)
    model.open_error = None
    model.pieces, model.stream_error = [], f"401 for Bearer {TRIAL_KEY}"
    streamed = send(client, chat_id)

    assert refused.status_code == 502 and TRIAL_KEY not in refused.text and "Incorrect API key" in refused.text
    assert TRIAL_KEY not in streamed.text and "error" in streamed.text


def test_get_client_builds_the_sdk_client_from_the_server_key(idp, monkeypatch):
    built = {}

    class Sdk:
        def __init__(self, **kw):
            built.update(kw)

    monkeypatch.setattr(providers, "OpenAI", Sdk)
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    profile = providers.active_profile(UserView(id=uid, username="u", is_admin=False))

    providers.get_client(profile, UserView(id=uid, username="u", is_admin=False))

    assert (built["api_key"], built["base_url"]) == (TRIAL_KEY, "https://api.deepseek.com")


def test_parallel_chat_creation_cannot_pass_the_trial_cap(idp):
    client = trial_client(idp)
    uid = client.get("/api/auth/me").json()["id"]
    cap = 5
    results = []

    def make():
        try:
            runtime.db.create_chat("trial", owner=uid, max_chats=cap)
            results.append(True)
        except storage.ChatLimit:
            results.append(False)

    threads = [threading.Thread(target=make) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count(True) == cap and runtime.db.count_chats(owner=uid) == cap
