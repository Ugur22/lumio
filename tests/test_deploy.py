import json
import stat

import pytest
from models import LOCAL_USER, UserView
from fastapi.testclient import TestClient

import secret_store
import server
import profile_store
from app import auth, runtime, routes_profiles

SECRET = "sk-test-1234567890abcd"
HOST = "lumio.example.com"


def make(api, **over):
    body = {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "m1", "key": SECRET} | over
    return api.post("/api/profiles", json=body)


@pytest.fixture
def secrets_file(tmp_path, monkeypatch, master_key):
    path = tmp_path / "secrets.json"
    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, str(path))
    return path


USER = UserView(id="c" * 32, username="writer", is_admin=False)


@pytest.fixture(autouse=True)
def signed_in_when_deployed():
    # Login itself is covered in test_accounts.py; here the caller is fixed so the host and origin checks stand alone.
    server.app.dependency_overrides[auth.current_user] = lambda: USER if runtime.settings.deployed else LOCAL_USER
    yield
    server.app.dependency_overrides.pop(auth.current_user, None)


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    origin = f"https://{HOST}"
    return TestClient(server.app, base_url=origin, headers={"Origin": origin})


def test_file_store_round_trips_keys_and_bypasses_the_keychain(secrets_file, memory_keyring):
    secret_store.set_key(SECRET, "profile:a")
    secret_store.set_key("other-key-123456", "profile:b")

    assert secret_store.get_key("profile:a") == SECRET
    stored = json.loads(secrets_file.read_text())["secrets"]
    assert set(stored) == {"profile:a", "profile:b"} and SECRET not in secrets_file.read_text()
    assert memory_keyring.store == {}

    secret_store.delete_key("profile:a")
    secret_store.delete_key("profile:missing")

    assert secret_store.get_key("profile:a") is None
    assert secret_store.get_key("profile:b") == "other-key-123456"


def test_file_store_is_owner_only_and_leaves_no_temp_file(secrets_file):
    secret_store.set_key(SECRET, "profile:a")
    secret_store.set_key(SECRET, "profile:a")

    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    assert {p.name for p in secrets_file.parent.iterdir()} == {secrets_file.name, secrets_file.name + ".lock"}


def test_file_store_reads_a_corrupt_file_as_empty_but_refuses_to_overwrite_it(secrets_file):
    secrets_file.write_text("not json")

    assert secret_store.get_key("profile:a") is None
    with pytest.raises(secret_store.SecretStoreError):
        secret_store.set_key(SECRET, "profile:a")
    assert secrets_file.read_text() == "not json"


def test_profile_keys_land_in_the_file_and_never_in_profiles_json(api, secrets_file):
    res = make(api)
    pid = res.json()["profiles"][-1]["id"]

    assert secret_store.get_key(f"profile:{pid}") == SECRET and SECRET not in secrets_file.read_text()
    assert SECRET not in runtime.settings.profiles_file.read_text() and SECRET not in res.text


def test_key_store_reports_file_on_a_server_and_keychain_locally(api, memory_keyring, monkeypatch, master_key):
    local = make(api).json()["profiles"][-1]
    assert (local["key_store"], api.get("/api/web").json()["key_store"]) == ("keychain", "keychain")

    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, "/unused/secrets.json")
    assert api.get("/api/web").json()["key_store"] == "file"
    assert {p["key_store"] for p in api.get("/api/profiles").json()["profiles"]} == {"file"}


def test_public_host_may_write_but_other_hosts_still_may_not(remote, api):
    assert make(remote).status_code == 201

    res = api.post("/api/profiles", json={}, headers={"Host": "attacker.example", "Origin": "http://attacker.example"})
    assert res.status_code == 403


def test_public_host_rejects_a_foreign_origin(remote):
    res = remote.post("/api/profiles", json={}, headers={"Origin": "https://evil.example"})

    assert res.status_code == 403


def test_localhost_is_unaffected_when_deployed(api, monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)

    assert make(api).status_code == 201


def test_deployed_edit_cannot_move_a_saved_key_to_another_url(remote):
    pid = make(remote).json()["profiles"][-1]["id"]

    res = remote.patch(f"/api/profiles/{pid}", json={"base_url": "https://attacker.example/v1"})

    assert res.status_code == 403
    profile = profile_store.load_store(runtime.settings, USER).profiles[-1]
    assert profile.base_url == "https://openrouter.ai/api/v1"


def test_deployed_edit_may_move_the_url_when_the_key_is_entered_again(remote):
    pid = make(remote).json()["profiles"][-1]["id"]

    res = remote.patch(f"/api/profiles/{pid}", json={"base_url": "https://other.example/v1", "key": "new-key-123456789"})

    assert res.status_code == 200


def test_deployed_edit_of_other_fields_or_the_same_url_still_works(remote):
    pid = make(remote).json()["profiles"][-1]["id"]

    res = remote.patch(f"/api/profiles/{pid}", json={"model": "m2", "base_url": "https://openrouter.ai/api/v1/"})

    assert res.status_code == 200


def test_deployed_model_listing_will_not_send_a_saved_key_to_another_url(remote, monkeypatch):
    pid = make(remote).json()["profiles"][-1]["id"]
    monkeypatch.setattr(routes_profiles, "OpenAI", lambda **kw: pytest.fail("a client was built for the foreign URL"))

    res = remote.post("/api/profiles/models", json={"profile_id": pid, "base_url": "https://attacker.example/v1"})

    assert res.status_code == 403


def test_local_edit_keeps_the_saved_key_when_the_url_changes(api):
    pid = make(api).json()["profiles"][-1]["id"]

    res = api.patch(f"/api/profiles/{pid}", json={"base_url": "https://other.example/v1"})

    assert res.status_code == 200
