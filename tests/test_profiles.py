import pytest
from conftest import FakeStream
from openai import OpenAIError

import secret_store
import server

SECRET = "sk-test-1234567890abcd"


def make(api, **over):
    body = {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "m1", "key": SECRET} | over
    return api.post("/api/profiles", json=body)


def by_name(res, name):
    return next(p for p in res.json()["profiles"] if p["name"] == name)


def test_legacy_env_key_migrates_to_a_default_dolphin_profile(api):
    res = api.get("/api/profiles").json()

    assert res["active"] == "default"
    (p,) = res["profiles"]
    assert (p["name"], p["source"], p["configured"]) == ("Dolphin", "env", True)
    assert p["last4"] is None and "test-key" not in str(res)


def test_fresh_install_starts_empty(api, monkeypatch):
    monkeypatch.setattr(server.settings, "api_key", None)

    assert api.get("/api/profiles").json() == {"active": None, "profiles": []}


def test_created_profile_stores_key_in_keychain_and_never_returns_it(api, memory_keyring):
    res = make(api)

    assert res.status_code == 201
    p = by_name(res, "OpenRouter")
    assert (p["configured"], p["last4"], p["source"]) == (True, "abcd", "keychain")
    assert SECRET not in res.text and SECRET not in api.get("/api/profiles").text
    assert memory_keyring.store[(secret_store.SERVICE, f"profile:{p['id']}")] == SECRET
    assert server.settings.profiles_file.exists()
    assert SECRET not in server.settings.profiles_file.read_text()


def test_first_profile_becomes_active_and_is_used_for_chat(api, monkeypatch, fake_client):
    monkeypatch.setattr(server.settings, "api_key", None)
    seen = {}

    def create(model, messages, stream, **kw):
        seen["model"] = model
        return FakeStream([])

    fake_client.chat.completions.create = create
    make(api, model="gpt-x")
    cid = api.post("/api/chats").json()["id"]
    api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert seen["model"] == "gpt-x"


def test_activate_switches_the_provider_used(api):
    other = by_name(make(api, name="Other", model="m2"), "Other")["id"]

    res = api.post(f"/api/profiles/{other}/activate")

    assert res.json()["active"] == other
    assert server.active_profile().model == "m2"


def test_edit_updates_fields_and_replaces_key(api, memory_keyring):
    pid = by_name(make(api), "OpenRouter")["id"]

    res = api.patch(f"/api/profiles/{pid}", json={"model": "m9", "key": "sk-other-0000000000zzzz"})

    p = by_name(res, "OpenRouter")
    assert (p["model"], p["last4"]) == ("m9", "zzzz")
    assert memory_keyring.store[(secret_store.SERVICE, f"profile:{pid}")].endswith("zzzz")


def test_edit_without_key_keeps_the_saved_key(api):
    pid = by_name(make(api), "OpenRouter")["id"]

    res = api.patch(f"/api/profiles/{pid}", json={"name": "Renamed"})

    assert by_name(res, "Renamed")["last4"] == "abcd"


def test_delete_removes_key_and_moves_active(api, memory_keyring):
    pid = by_name(make(api), "OpenRouter")["id"]
    api.post(f"/api/profiles/{pid}/activate")

    res = api.delete(f"/api/profiles/{pid}")

    assert res.json()["active"] == "default"
    assert (secret_store.SERVICE, f"profile:{pid}") not in memory_keyring.store


def test_deleting_default_also_clears_the_legacy_keychain_key(api, memory_keyring):
    secret_store.set_key("legacy-key-123456")

    api.delete("/api/profiles/default")

    assert memory_keyring.store == {}


def test_legacy_keychain_key_still_works_for_default(api, monkeypatch):
    monkeypatch.setattr(server.settings, "api_key", None)
    secret_store.set_key("legacy-key-123456")

    p = api.get("/api/profiles").json()["profiles"][0]

    assert (p["name"], p["source"], p["last4"]) == ("Dolphin", "keychain", "3456")


def test_unknown_profile_is_404(api):
    assert api.post("/api/profiles/nope/activate").status_code == 404
    assert api.delete("/api/profiles/nope").status_code == 404


@pytest.mark.parametrize(
    "url",
    ["ftp://x.example/v1", "http://api.example.com/v1", "https://user:pw@api.example.com", "not a url", ""],
)
def test_bad_base_urls_are_rejected(api, url):
    assert make(api, base_url=url).status_code == 422


def test_http_is_allowed_for_localhost_and_slash_is_trimmed(api):
    res = make(api, name="Ollama", base_url="http://localhost:11434/v1/", needs_key=False, key=None)

    assert by_name(res, "Ollama")["base_url"] == "http://localhost:11434/v1"
    assert by_name(res, "Ollama")["configured"] is True


def test_validation_errors_do_not_echo_the_key(api):
    res = make(api, key="x" * 600)

    assert res.status_code == 422
    assert "x" * 50 not in res.text


def test_no_provider_gives_a_clear_conflict_on_send(api, monkeypatch):
    monkeypatch.setattr(server.settings, "api_key", None)
    cid = api.post("/api/chats").json()["id"]

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert res.status_code == 409 and "Providers" in res.json()["detail"]
    assert api.get(f"/api/chats/{cid}").json()["messages"] == []


def test_profile_without_key_gives_a_conflict_naming_it(api):
    pid = by_name(make(api, key=None), "OpenRouter")["id"]
    api.post(f"/api/profiles/{pid}/activate")
    cid = api.post("/api/chats").json()["id"]

    res = api.post(f"/api/chats/{cid}/messages", json={"content": "hi"})

    assert res.status_code == 409 and "OpenRouter" in res.json()["detail"]


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "http://localhost:9999"}, {"Origin": "null"}])
def test_cross_origin_writes_are_refused(api, headers):
    assert api.post("/api/profiles", json={}, headers=headers).status_code == 403
    assert api.delete("/api/profiles/default", headers=headers).status_code == 403
    assert api.post("/api/profiles/models", json={}, headers=headers).status_code == 403


def test_missing_origin_and_non_local_host_are_refused(api):
    api.headers.pop("Origin")
    assert make(api).status_code == 403

    res = api.post(
        "/api/profiles/models", json={}, headers={"Host": "attacker.example", "Origin": "http://attacker.example"}
    )
    assert res.status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_vite_dev_origin_is_accepted_even_if_the_proxy_rewrites_host(api, origin):
    res = api.post("/api/profiles", json={"name": "V", "base_url": "https://a.example/v1", "model": "m"}, headers={"Origin": origin})
    assert res.status_code == 201


def test_refusal_says_why_without_leaking_the_key(api):
    res = api.post(
        "/api/profiles",
        json={"name": "x", "base_url": "https://a.example/v1", "model": "m", "key": SECRET},
        headers={"Origin": "https://evil.example"},
    )

    assert res.status_code == 403 and "evil.example" in res.json()["detail"] and SECRET not in res.text


def test_status_read_works_without_an_origin_header(api):
    api.headers.pop("Origin")

    assert api.get("/api/profiles").status_code == 200


class FakeOpenAI:
    """Stands in for openai.OpenAI inside the models endpoint."""

    seen = []

    def __init__(self, base_url, api_key):
        FakeOpenAI.seen.append((base_url, api_key))
        self.models = type("M", (), {"list": staticmethod(self._list)})

    def _list(self):
        if FakeOpenAI.fail:
            raise OpenAIError(f"Incorrect API key provided: {FakeOpenAI.fail}")
        return [type("Mod", (), {"id": i})() for i in ("b-model", "a-model")]

    def close(self):
        pass

    fail = None


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.seen, FakeOpenAI.fail = [], None
    monkeypatch.setattr(server, "OpenAI", FakeOpenAI)
    return FakeOpenAI


def test_models_for_an_unsaved_provider_uses_the_typed_url_and_key(api, fake_openai):
    res = api.post("/api/profiles/models", json={"base_url": "https://api.x.example/v1", "key": SECRET})

    assert res.json() == {"models": ["a-model", "b-model"]}
    assert fake_openai.seen == [("https://api.x.example/v1", SECRET)]


def test_models_for_a_saved_profile_uses_its_stored_key(api, fake_openai):
    pid = by_name(make(api), "OpenRouter")["id"]

    api.post("/api/profiles/models", json={"profile_id": pid})

    assert fake_openai.seen == [("https://openrouter.ai/api/v1", SECRET)]


def test_models_without_any_key_is_a_conflict_unless_the_provider_needs_none(api, fake_openai):
    url = {"base_url": "http://localhost:11434/v1"}

    assert api.post("/api/profiles/models", json=url).status_code == 409
    assert api.post("/api/profiles/models", json=url | {"needs_key": False}).status_code == 200


def test_models_errors_redact_the_key(api, fake_openai):
    fake_openai.fail = SECRET

    res = api.post("/api/profiles/models", json={"base_url": "https://api.x.example/v1", "key": SECRET})

    assert res.status_code == 502 and SECRET not in res.text


def test_client_is_rebuilt_when_the_key_changes(api):
    pid = by_name(make(api), "OpenRouter")["id"]
    profile = server.find(server.profile_store.load_store(server.settings), pid)
    first = server.get_client(profile)

    api.patch(f"/api/profiles/{pid}", json={"key": "sk-other-0000000000zzzz"})

    assert server.get_client(profile) is not first


def test_keychain_failure_on_save_is_a_503(api, monkeypatch):
    def boom(*_):
        raise RuntimeError("locked")

    monkeypatch.setattr(secret_store, "set_key", boom)

    assert make(api).status_code == 503


def test_corrupt_profiles_file_is_set_aside_not_overwritten(api):
    server.settings.profiles_file.write_text("{not json")

    assert api.get("/api/profiles").status_code == 200
    assert server.settings.profiles_file.with_suffix(".corrupt").exists()
    server.settings.profiles_file.with_suffix(".corrupt").unlink()
