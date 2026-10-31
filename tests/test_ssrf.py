"""Provider URLs on a server: internal addresses are refused when saved and again when used (DNS can change)."""

import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import OpenAIError

import server
from app import auth, providers, routes_profiles, runtime
from models import LOCAL_USER, Profile, UserView

HOST = "lumio.example.com"
USER = UserView(id="c" * 32, username="writer", is_admin=False)
KEY = "sk-test-1234567890abcd"
INTERNAL = [
    "http://127.0.0.1:11434/v1",
    "http://localhost:11434/v1",
    "https://169.254.169.254/latest/meta-data",
    "https://10.0.0.5/v1",
    "https://192.168.1.10/v1",
    "https://172.16.0.1/v1",
    "https://0.0.0.0/v1",
    "https://[::1]/v1",
    "https://[::ffff:127.0.0.1]/v1",
    "https://internal.example/v1",  # a name that resolves to 10.1.2.3 (see the dns table below)
]


@pytest.fixture(autouse=True)
def signed_in(dns):
    dns["internal.example"] = "10.1.2.3"
    server.app.dependency_overrides[auth.current_user] = lambda: USER if runtime.settings.deployed else LOCAL_USER
    yield
    server.app.dependency_overrides.pop(auth.current_user, None)


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    origin = f"https://{HOST}"
    return TestClient(server.app, base_url=origin, headers={"Origin": origin})


def models_client(listing):
    return lambda **kw: type("C", (), {"models": type("L", (), {"list": staticmethod(listing)}), "close": lambda self: None})()


def create(client, url="https://openrouter.ai/api/v1", **over):
    body = {"name": "P", "base_url": url, "model": "m1", "key": KEY} | over
    return client.post("/api/profiles", json=body)


def profile_ids(client):
    return [p["id"] for p in client.get("/api/profiles").json()["profiles"]]


@pytest.mark.parametrize("url", INTERNAL)
def test_deployed_create_refuses_internal_urls(remote, url):
    res = create(remote, url)

    assert res.status_code == 422
    assert providers.PRIVATE_URL in res.text
    assert profile_ids(remote) == []


def test_deployed_create_refuses_an_out_of_range_port_instead_of_failing(remote):
    res = create(remote, "https://example.com:99999/v1")

    assert res.status_code == 422
    assert profile_ids(remote) == []


def test_deployed_create_accepts_a_public_name(remote):
    assert create(remote).status_code == 201


def test_deployed_edit_refuses_a_move_to_an_internal_url_even_with_a_new_key(remote):
    pid = create(remote).json()["profiles"][-1]["id"]

    res = remote.patch(f"/api/profiles/{pid}", json={"base_url": "https://169.254.169.254/v1", "key": "another-key-123456"})

    assert res.status_code == 422
    assert remote.get("/api/profiles").json()["profiles"][0]["base_url"] == "https://openrouter.ai/api/v1"


@pytest.mark.parametrize("url", ["https://169.254.169.254/v1", "http://127.0.0.1:8000/v1", "https://internal.example/v1"])
def test_deployed_model_listing_refuses_internal_urls_before_building_a_client(remote, monkeypatch, url):
    monkeypatch.setattr(routes_profiles, "OpenAI", lambda **kw: pytest.fail("a client was built for an internal URL"))

    res = remote.post("/api/profiles/models", json={"base_url": url, "key": KEY})

    assert res.status_code == 422


def test_local_mode_still_allows_loopback_providers(api):
    for url in ("http://127.0.0.1:11434/v1", "http://localhost:11434/v1"):
        assert create(api, url, needs_key=False, key=None).status_code == 201


def test_local_model_listing_allows_loopback(api, monkeypatch):
    monkeypatch.setattr(routes_profiles, "OpenAI", models_client(lambda: [type("M", (), {"id": "llama"})()]))

    res = api.post("/api/profiles/models", json={"base_url": "http://127.0.0.1:11434/v1", "needs_key": False})

    assert res.status_code == 200 and res.json()["models"] == ["llama"]


# --- use time: DNS rebinding ---------------------------------------------------------------------


def stored_profile(url="https://rebind.example/v1"):
    return Profile(id="p1", name="P", base_url=url, model="m")


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(providers, "profile_key", lambda profile, user: "k")
    monkeypatch.setattr(providers, "OpenAI", lambda **kw: object())
    providers._clients.clear()
    yield
    providers._clients.clear()


def test_a_name_that_turns_internal_is_refused_when_the_client_is_used(remote, keyed, dns):
    profile = stored_profile()
    providers.get_client(profile, USER)  # public now, and cached

    dns["rebind.example"] = "169.254.169.254"

    with pytest.raises(HTTPException) as e:
        providers.get_client(profile, USER)  # the cached client must not skip the check

    assert e.value.status_code == 422


def test_a_profile_saved_with_an_internal_url_cannot_send(remote, keyed):
    with pytest.raises(HTTPException) as e:
        providers.get_client(stored_profile("http://127.0.0.1:9/v1"), USER)

    assert e.value.status_code == 422


def test_local_mode_does_not_check_at_use_time(keyed):
    providers.get_client(stored_profile("http://127.0.0.1:11434/v1"), LOCAL_USER)


def test_models_error_text_is_hidden_when_the_host_turned_internal(remote, monkeypatch, dns):
    def listing():
        dns["rebind.example"] = "10.9.9.9"  # flips after the pre-check, as a rebinding attack would
        raise OpenAIError("secret body from an internal service")

    monkeypatch.setattr(routes_profiles, "OpenAI", models_client(listing))

    res = remote.post("/api/profiles/models", json={"base_url": "https://rebind.example/v1", "key": KEY})

    assert res.status_code == 502
    assert "secret body" not in res.text


def test_models_error_text_is_kept_for_a_public_host(remote, monkeypatch):
    def listing():
        raise OpenAIError("Invalid API key")

    monkeypatch.setattr(routes_profiles, "OpenAI", models_client(listing))

    res = remote.post("/api/profiles/models", json={"base_url": "https://api.example/v1", "key": KEY})

    assert res.status_code == 502 and "Invalid API key" in res.text


def test_a_server_client_does_not_follow_redirects(remote):
    assert providers.client_options()["http_client"].follow_redirects is False


def test_a_local_client_keeps_the_sdk_defaults(api):
    assert providers.client_options() == {}


# --- item 12: a whitespace-only key is no key ----------------------------------------------------


def test_deployed_edit_with_a_blank_key_cannot_redirect_the_saved_key(remote):
    pid = create(remote).json()["profiles"][-1]["id"]

    res = remote.patch(f"/api/profiles/{pid}", json={"base_url": "https://attacker.example/v1", "key": "   "})

    assert res.status_code == 403
    assert remote.get("/api/profiles").json()["profiles"][0]["base_url"] == "https://openrouter.ai/api/v1"


def test_deployed_model_listing_with_a_blank_key_cannot_redirect_the_saved_key(remote, monkeypatch):
    pid = create(remote).json()["profiles"][-1]["id"]
    monkeypatch.setattr(routes_profiles, "OpenAI", lambda **kw: pytest.fail("the saved key was sent to a foreign URL"))

    res = remote.post("/api/profiles/models", json={"profile_id": pid, "base_url": "https://attacker.example/v1", "key": "  \t "})

    assert res.status_code == 403


# --- item 8: the client cache under threads ------------------------------------------------------


class ClearsAfterStore(dict):
    """Another thread's clear() landing right after the assignment."""

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self.clear()


def test_get_client_survives_the_cache_being_cleared_right_after_it_stores(remote, monkeypatch):
    monkeypatch.setattr(providers, "profile_key", lambda profile, user: "k")
    monkeypatch.setattr(providers, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(providers, "_clients", ClearsAfterStore())

    assert providers.get_client(stored_profile("https://api.example/v1"), USER) is not None


def test_get_client_from_many_threads_never_fails(remote, monkeypatch):
    monkeypatch.setattr(providers, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(providers, "profile_key", lambda profile, user: f"key-{threading.get_ident() % 7}")
    providers._clients.clear()
    errors = []

    def work():
        try:
            for _ in range(200):
                providers.get_client(stored_profile("https://api.example/v1"), USER)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == []
    providers._clients.clear()
