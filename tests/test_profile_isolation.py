"""Profiles, their API keys and the web-search key belong to one user.

Identity is faked like in test_ownership.py (an X-Test-User header overrides `auth.current_user`); the upstream is a
recording fake, so the assertions are on the key a provider would really have received.
"""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import profile_store
import secret_store
import server
import web
from app import auth, providers, routes_profiles, runtime
import conftest
from conftest import ORIGIN, FakeStream, REPLY_PIECES
from models import LOCAL_USER, Profile, ProfileStore, UserView

A, B = "a" * 32, "b" * 32
KEY_A, KEY_B = "sk-alice-key-111111", "sk-bobby-key-222222"
TAVILY_A, TAVILY_B = "tvly-alice-key-1111", "tvly-bobby-key-2222"
HOST = "lumio.example.com"
HTTPS = f"https://{HOST}"


def user(uid: str, name: str | None = None) -> UserView:
    return UserView(id=uid, username=name or uid, is_admin=False)


@pytest.fixture(autouse=True)
def header_identity():
    def who(request: Request):
        return user(request.headers["x-test-user"])

    server.app.dependency_overrides[auth.current_user] = who
    yield
    server.app.dependency_overrides.pop(auth.current_user, None)


def client_for(uid: str, base=ORIGIN) -> TestClient:
    return TestClient(server.app, base_url=base, headers={"Origin": base, "X-Test-User": uid})


@pytest.fixture
def alice():
    return client_for(A)


@pytest.fixture
def bob():
    return client_for(B)


class FakeClient(conftest.FakeClient):
    def close(self):
        pass


@pytest.fixture
def upstream(monkeypatch):
    """Replaces the SDK client: records the api key each request is made with, and what the web search is given."""
    seen = {"keys": [], "tavily": [], "listed": []}

    def fake_openai(base_url, api_key, **_):
        seen["keys"].append(api_key)
        return FakeClient(
            create=lambda **kw: FakeStream(REPLY_PIECES),
            models=lambda: [type("M", (), {"id": "m1"})()],
        )

    def fake_models_openai(base_url, api_key, **_):
        seen["listed"].append(api_key)
        return FakeClient(models=lambda: [type("M", (), {"id": "m1"})()])

    def fake_gather(content, enabled, tavily_key, query=None):
        seen["tavily"].append(tavily_key)
        return [], []

    monkeypatch.setattr(providers, "OpenAI", fake_openai)
    monkeypatch.setattr(routes_profiles, "OpenAI", fake_models_openai)
    monkeypatch.setattr(web, "gather", fake_gather)
    monkeypatch.setattr(web, "rewrite_query", lambda *a, **k: None)
    providers._clients.clear()
    yield seen
    providers._clients.clear()


def make(api, key=KEY_A, **over):
    body = {"name": "Prov", "base_url": "https://x.example/v1", "model": "m1", "key": key} | over
    res = api.post("/api/profiles", json=body)
    assert res.status_code == 201, res.text
    return res.json()["profiles"][-1]["id"]


def send(api, chat_id, **over):
    res = api.post(f"/api/chats/{chat_id}/messages", json={"content": "hello"} | over)
    assert res.status_code == 200, res.text
    return res


# --- isolation of profiles ------------------------------------------------------------------------------------------


def test_each_user_sees_only_their_own_profiles_and_key_tail(alice, bob):
    pa = make(alice, KEY_A)
    pb = make(bob, KEY_B)

    a_list, b_list = alice.get("/api/profiles").json(), bob.get("/api/profiles").json()

    assert [p["id"] for p in a_list["profiles"]] == [pa] and a_list["profiles"][0]["last4"] == KEY_A[-4:]
    assert [p["id"] for p in b_list["profiles"]] == [pb] and b_list["profiles"][0]["last4"] == KEY_B[-4:]
    assert KEY_A[-4:] not in json.dumps(b_list)


def test_a_new_user_starts_with_no_provider_even_though_the_env_key_exists(bob):
    assert runtime.settings.api_key  # the suite sets one; only the local user and the admin may inherit it
    assert bob.get("/api/profiles").json() == {"active": None, "profiles": []}


def test_another_users_profile_answers_404_on_every_route(alice, bob):
    pa = make(alice)
    mine = make(bob, KEY_B)

    attempts = [
        bob.patch(f"/api/profiles/{pa}", json={"name": "stolen"}),
        bob.patch(f"/api/profiles/{pa}", json={"key": "sk-overwrite-12345678"}),
        bob.delete(f"/api/profiles/{pa}"),
        bob.post(f"/api/profiles/{pa}/activate"),
        bob.post("/api/profiles/models", json={"profile_id": pa}),
        bob.post("/api/profiles/models", json={"profile_id": "0" * 8}),  # a missing one, for comparison
    ]

    assert [r.status_code for r in attempts] == [404] * 6
    assert len({r.text for r in attempts}) == 1  # nothing tells "exists" from "missing"
    assert [p["id"] for p in bob.get("/api/profiles").json()["profiles"]] == [mine]
    after = alice.get("/api/profiles").json()["profiles"][0]
    assert (after["name"], after["last4"]) == ("Prov", KEY_A[-4:])
    assert secret_store.get_key(profile_store.profile_account(user(A), pa)) == KEY_A


def test_models_listing_for_own_profile_uses_own_key(alice, bob, upstream):
    make(alice, KEY_A)
    pb = make(bob, KEY_B)

    assert bob.post("/api/profiles/models", json={"profile_id": pb}).status_code == 200
    assert upstream["listed"] == [KEY_B]


def test_deleting_one_users_profile_leaves_the_others_secret(alice, bob):
    pa = make(alice, KEY_A)
    pb = make(bob, KEY_B)

    assert bob.delete(f"/api/profiles/{pb}").status_code == 200

    assert secret_store.get_key(profile_store.profile_account(user(A), pa)) == KEY_A
    assert secret_store.get_key(profile_store.profile_account(user(B), pb)) is None
    assert alice.get("/api/profiles").json()["profiles"][0]["last4"] == KEY_A[-4:]


def test_equal_profile_ids_in_two_stores_do_not_collide_in_secrets(alice, bob, monkeypatch):
    monkeypatch.setattr(routes_profiles, "new_profile_id", lambda: "samesame")
    assert make(alice, KEY_A) == make(bob, KEY_B) == "samesame"

    assert secret_store.get_key(f"u:{A}:profile:samesame") == KEY_A
    assert secret_store.get_key(f"u:{B}:profile:samesame") == KEY_B
    assert secret_store.get_key("profile:samesame") is None
    bob.patch("/api/profiles/samesame", json={"key": "sk-bobby-rotated-3333"})
    bob.delete("/api/profiles/samesame")
    assert secret_store.get_key(f"u:{A}:profile:samesame") == KEY_A
    assert alice.get("/api/profiles").json()["profiles"][0]["last4"] == KEY_A[-4:]


def test_a_user_with_a_taken_id_gets_a_fresh_one(alice, monkeypatch):
    ids = iter(["dupe0001", "dupe0001", "dupe0002"])
    monkeypatch.setattr(routes_profiles, "new_profile_id", lambda: next(ids))

    assert (make(alice), make(alice)) == ("dupe0001", "dupe0002")


def test_profile_files_are_per_user_and_atomic(alice, bob):
    make(alice, KEY_A)
    make(bob, KEY_B)
    base = runtime.settings.profiles_file.parent / "profiles"

    assert sorted(p.name for p in base.iterdir()) == sorted([f"{A}.json", f"{B}.json"])
    assert not runtime.settings.profiles_file.exists()  # the local user's file is untouched by other users
    assert KEY_A not in (base / f"{A}.json").read_text()


def test_local_user_keeps_the_legacy_file_and_account_names(api):
    server.app.dependency_overrides.pop(auth.current_user)  # the real dependency: the fixed local user
    pid = make(api, KEY_A)

    assert profile_store.store_path(runtime.settings, LOCAL_USER) == runtime.settings.profiles_file
    assert runtime.settings.profiles_file.exists()
    assert secret_store.get_key(f"profile:{pid}") == KEY_A
    api.put("/api/web/key", json={"key": TAVILY_A})
    assert secret_store.get_key("tavily") == TAVILY_A


# --- which key a send uses ------------------------------------------------------------------------------------------


def test_a_send_uses_the_callers_key_and_never_anothers(alice, bob, upstream):
    make(alice, KEY_A)
    make(bob, KEY_B)

    send(bob, bob.post("/api/chats").json()["id"])
    send(alice, alice.post("/api/chats").json()["id"])

    assert upstream["keys"] == [KEY_B, KEY_A]


def test_a_chat_pointing_at_another_users_profile_falls_back_to_the_callers(alice, bob, upstream):
    pa = make(alice, KEY_A)
    pb = make(bob, KEY_B)
    chat_id = bob.post("/api/chats").json()["id"]
    # Forced past the route (which refuses it): as if the id were left over from a deleted or foreign profile.
    runtime.db.update_behavior(chat_id, {}, True, pa, owner=B)
    assert bob.get(f"/api/chats/{chat_id}").json()["profile_id"] == pa

    send(bob, chat_id)

    assert upstream["keys"] == [KEY_B]
    assert providers.profile_for(runtime.db.get_chat(chat_id, owner=B), user(B)).id == pb
    assert bob.get(f"/api/chats/{chat_id}/context").status_code == 200


def test_a_chat_cannot_be_given_another_users_profile(alice, bob):
    pa = make(alice)
    pb = make(bob, KEY_B)
    chat_id = bob.post("/api/chats").json()["id"]

    res = bob.put(f"/api/chats/{chat_id}/behavior", json={"profile_id": pa})

    assert res.status_code == 404
    assert bob.get(f"/api/chats/{chat_id}").json()["profile_id"] == pb  # still the one it was created with


def test_a_user_without_a_provider_cannot_borrow_one(alice, bob, upstream):
    make(alice, KEY_A)
    chat_id = bob.post("/api/chats").json()["id"]

    res = bob.post(f"/api/chats/{chat_id}/messages", json={"content": "hi"})

    assert res.status_code == 409 and upstream["keys"] == []


def test_the_web_search_key_is_per_user(alice, bob, upstream):
    make(alice, KEY_A)
    make(bob, KEY_B)
    assert alice.put("/api/web/key", json={"key": TAVILY_A}).json()["configured"]
    assert bob.get("/api/web").json() == {"configured": False, "last4": None, "key_store": "keychain"}
    bob.put("/api/web/key", json={"key": TAVILY_B})

    send(bob, bob.post("/api/chats").json()["id"], web=True)
    send(alice, alice.post("/api/chats").json()["id"], web=True)

    assert upstream["tavily"] == [TAVILY_B, TAVILY_A]
    assert secret_store.get_key(f"u:{A}:tavily") == TAVILY_A
    bob.delete("/api/web/key")
    assert alice.get("/api/web").json()["last4"] == TAVILY_A[-4:]
    assert secret_store.get_key("tavily") is None


def test_deployed_url_guard_and_key_redirect_refusal_apply_per_user(alice, bob, monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    a, b = client_for(A, HTTPS), client_for(B, HTTPS)
    pa = make(a, KEY_A)
    make(b, KEY_B)

    assert b.patch(f"/api/profiles/{pa}", json={"base_url": "https://evil.example/v1"}).status_code == 404
    assert a.patch(f"/api/profiles/{pa}", json={"base_url": "https://evil.example/v1"}).status_code == 403
    assert a.post("/api/profiles/models", json={"profile_id": pa, "base_url": "https://evil.example/v1"}).status_code == 403


# --- path and account safety ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "", "a" * 32 + ".json/..", "u:x", "A" * 32, "g" * 32])
def test_unsafe_user_ids_never_become_a_path_or_an_account(bad):
    with pytest.raises(AssertionError):
        profile_store.store_path(runtime.settings, user(bad))
    with pytest.raises(AssertionError):
        profile_store.profile_account(user(bad), "p1")
    with pytest.raises(AssertionError):
        profile_store.tavily_account(user(bad))


@pytest.mark.parametrize("bad", ["a:profile:b", "x/y", "", "a b"])
def test_secret_account_parts_cannot_forge_another_account(bad):
    with pytest.raises(ValueError):
        secret_store.user_profile_account(bad, "p1")
    with pytest.raises(ValueError):
        secret_store.user_profile_account(A, bad)
    with pytest.raises(ValueError):
        secret_store.user_tavily_account(bad)


def test_the_admin_inherits_the_env_key_but_other_users_do_not(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    monkeypatch.setattr(runtime.settings, "admin_user", "Boss ")
    boss, other = user(A, "boss"), user(B, "other")

    store = profile_store.load_store(runtime.settings, boss)
    assert [p.id for p in store.profiles] == [profile_store.DEFAULT_ID]
    assert profile_store.resolve_key(runtime.settings, boss, store.profiles[0]) == (runtime.settings.api_key, "env")
    assert profile_store.load_store(runtime.settings, other) == ProfileStore()
    assert profile_store.resolve_key(runtime.settings, other, store.profiles[0]) == (None, None)


# --- moving the global profiles to the admin ------------------------------------------------------------------------


@pytest.fixture
def admin(monkeypatch):
    name = f"boss{uuid.uuid4().hex[:8]}"
    account = runtime.db.create_user(name, "x")
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    monkeypatch.setattr(runtime.settings, "admin_user", name)
    yield user(account.id, name)
    runtime.db.set_meta(profile_store.MIGRATION_KEY, "")


def seed_globals(*ids):
    """A pre-accounts install: profiles.json plus keys under the legacy account names."""
    profiles = [Profile(id=i, name=f"P {i}", base_url="https://x.example/v1", model="m") for i in ids]
    profile_store.save_store(runtime.settings, LOCAL_USER, ProfileStore(active=ids[0], profiles=profiles))
    for i in ids:
        secret_store.set_key(f"sk-global-{i}-123456", secret_store.profile_account(i))
    secret_store.set_key(TAVILY_A, secret_store.TAVILY_ACCOUNT)


def test_migration_moves_profiles_and_keys_to_the_admin(admin, memory_keyring):
    seed_globals("p1", "p2")

    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    store = profile_store.load_store(runtime.settings, admin)
    assert [p.id for p in store.profiles] == ["p1", "p2"] and store.active == "p1"
    assert [profile_store.resolve_key(runtime.settings, admin, p) for p in store.profiles] == [
        ("sk-global-p1-123456", "keychain"),
        ("sk-global-p2-123456", "keychain"),
    ]
    assert secret_store.get_key(profile_store.tavily_account(admin)) == TAVILY_A
    # the originals are gone, so nobody else can reach them either
    assert not runtime.settings.profiles_file.exists()
    assert {k[1] for k in memory_keyring.store} == {
        profile_store.profile_account(admin, "p1"),
        profile_store.profile_account(admin, "p2"),
        profile_store.tavily_account(admin),
    }
    assert runtime.db.get_meta(profile_store.MIGRATION_KEY) == admin.id


def test_migration_runs_once_and_never_again(admin):
    seed_globals("p1")
    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)
    seed_globals("p9")  # data that shows up later is not swept into the admin's account

    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    assert [p.id for p in profile_store.load_store(runtime.settings, admin).profiles] == ["p1"]
    assert runtime.settings.profiles_file.exists()
    assert secret_store.get_key("profile:p9")


def test_the_migration_waits_for_another_worker_holding_the_lock(admin):
    import threading

    seed_globals("p1")
    done = threading.Event()
    with secret_store.file_lock(runtime.settings.profiles_file):
        t = threading.Thread(target=lambda: (profile_store.migrate_global_to_user(runtime.settings, admin), done.set()))
        t.start()
        assert not done.wait(0.5)  # blocked while the lock is held
    t.join(10)

    assert done.is_set()
    assert [p.id for p in profile_store.load_store(runtime.settings, admin).profiles] == ["p1"]


def test_the_move_itself_is_idempotent_after_an_interruption(admin):
    seed_globals("p1")
    # An earlier run copied everything and died before deleting anything.
    secret_store.set_key("sk-global-p1-123456", profile_store.profile_account(admin, "p1"))
    profile_store.save_store(runtime.settings, admin, profile_store.load_store(runtime.settings, LOCAL_USER))

    assert profile_store.migrate_global_to_user(runtime.settings, admin) == ["p1", "tavily"]
    assert profile_store.migrate_global_to_user(runtime.settings, admin) == []

    assert [p.id for p in profile_store.load_store(runtime.settings, admin).profiles] == ["p1"]
    assert secret_store.get_key(profile_store.profile_account(admin, "p1")) == "sk-global-p1-123456"


def test_a_failure_part_way_keeps_every_original_and_the_app_starts(admin, monkeypatch, caplog):
    seed_globals("p1", "p2")
    real = secret_store.set_key

    def flaky(key, account=secret_store.LEGACY_ACCOUNT):
        if account == profile_store.profile_account(admin, "p2"):
            raise RuntimeError(f"keychain locked while writing {key}")
        real(key, account)

    monkeypatch.setattr(secret_store, "set_key", flaky)
    with caplog.at_level(logging.WARNING, logger="dolphinllm"):
        runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)  # must not raise

    assert runtime.settings.profiles_file.exists()
    assert secret_store.get_key("profile:p1") == "sk-global-p1-123456"
    assert secret_store.get_key("profile:p2") == "sk-global-p2-123456"
    assert secret_store.get_key("tavily") == TAVILY_A
    assert not runtime.db.get_meta(profile_store.MIGRATION_KEY)
    assert "sk-global" not in caplog.text and TAVILY_A not in caplog.text
    assert "stay where they are" in caplog.text

    monkeypatch.setattr(secret_store, "set_key", real)  # the next start finishes the job
    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)
    assert not runtime.settings.profiles_file.exists()
    assert secret_store.get_key(profile_store.profile_account(admin, "p2")) == "sk-global-p2-123456"


def test_a_key_that_does_not_read_back_keeps_the_originals(admin, monkeypatch):
    seed_globals("p1")
    real = secret_store.set_key
    monkeypatch.setattr(secret_store, "set_key", lambda key, account=secret_store.LEGACY_ACCOUNT: real("sk-corrupted-000000", account) if account.startswith("u:") else real(key, account))

    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    assert runtime.settings.profiles_file.exists() and secret_store.get_key("profile:p1") == "sk-global-p1-123456"
    assert not runtime.db.get_meta(profile_store.MIGRATION_KEY)


def test_a_conflicting_admin_profile_or_key_keeps_the_originals(admin):
    seed_globals("p1")
    secret_store.set_key("sk-admin-own-key-9999", profile_store.profile_account(admin, "p1"))

    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    assert secret_store.get_key(profile_store.profile_account(admin, "p1")) == "sk-admin-own-key-9999"
    assert runtime.settings.profiles_file.exists() and secret_store.get_key("profile:p1")
    assert not runtime.db.get_meta(profile_store.MIGRATION_KEY)


def test_the_old_single_key_becomes_the_admins_default_profile(admin, memory_keyring):
    secret_store.set_key("sk-legacy-single-1234", secret_store.LEGACY_ACCOUNT)

    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    store = profile_store.load_store(runtime.settings, admin)
    assert [p.id for p in store.profiles] == ["default"]
    assert profile_store.resolve_key(runtime.settings, admin, store.profiles[0]) == ("sk-legacy-single-1234", "keychain")
    assert secret_store.get_key() is None


def test_migration_does_nothing_without_an_existing_admin(admin, monkeypatch):
    seed_globals("p1")

    monkeypatch.setattr(runtime.settings, "admin_user", None)
    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)
    monkeypatch.setattr(runtime.settings, "admin_user", "nobody-" + uuid.uuid4().hex[:6])
    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)
    monkeypatch.setattr(runtime.settings, "public_host", None)
    runtime.migrate_profiles_to_admin(runtime.db, runtime.settings)

    assert runtime.settings.profiles_file.exists() and secret_store.get_key("profile:p1")
    assert not runtime.db.get_meta(profile_store.MIGRATION_KEY)
    assert not (runtime.settings.profiles_file.parent / "profiles").exists()


def test_without_an_admin_the_globals_stay_unreadable_by_everyone_but_local(admin, monkeypatch):
    seed_globals("p1")
    monkeypatch.setattr(runtime.settings, "admin_user", None)
    bob = client_for(B)

    assert bob.get("/api/profiles").json()["profiles"] == []
    assert bob.get("/api/web").json()["configured"] is False
    assert [p.id for p in profile_store.load_store(runtime.settings, LOCAL_USER).profiles] == ["p1"]


# --- CSRF on the chat and profile routes -----------------------------------------------------------------------------

EVIL = {"Origin": "https://evil.example"}
VITE = {"Origin": "http://localhost:5173"}


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(runtime.settings, "public_host", HOST)
    return client_for(A, HTTPS)


def unsafe_calls(c, chat_id, profile_id, **headers):
    return {
        "POST /api/chats": c.post("/api/chats", headers=headers),
        "PATCH chat": c.patch(f"/api/chats/{chat_id}", json={"title": "t"}, headers=headers),
        "PUT story": c.put(f"/api/chats/{chat_id}/story", json={"bible": "b", "lore": []}, headers=headers),
        "POST messages": c.post(f"/api/chats/{chat_id}/messages", json={"content": "hi"}, headers=headers),
        "DELETE chat": c.delete(f"/api/chats/{chat_id}", headers=headers),
        "POST profile": c.post("/api/profiles", json={"name": "n", "base_url": "https://x.example/v1", "model": "m"}, headers=headers),
        "PATCH profile": c.patch(f"/api/profiles/{profile_id}", json={"name": "z"}, headers=headers),
        "POST activate": c.post(f"/api/profiles/{profile_id}/activate", headers=headers),
        "POST models": c.post("/api/profiles/models", json={"base_url": "https://x.example/v1", "key": "sk-probe-1234567890"}, headers=headers),
        "DELETE profile": c.delete(f"/api/profiles/{profile_id}", headers=headers),
        "PUT web key": c.put("/api/web/key", json={"key": TAVILY_A}, headers=headers),
        "DELETE web key": c.delete("/api/web/key", headers=headers),
    }


def test_cross_origin_writes_are_rejected_when_deployed(remote, upstream):
    pid = make(remote)
    chat_id = remote.post("/api/chats").json()["id"]

    results = unsafe_calls(remote, chat_id, pid, **EVIL)

    assert {name: r.status_code for name, r in results.items()} == dict.fromkeys(results, 403)
    # and none of them took effect
    assert remote.get(f"/api/chats/{chat_id}").json()["title"] != "t"
    assert [p["name"] for p in remote.get("/api/profiles").json()["profiles"]] == ["Prov"]
    assert upstream["keys"] == []


def test_a_write_without_an_origin_is_rejected_when_deployed(remote):
    raw = TestClient(server.app, base_url=HTTPS, headers={"X-Test-User": A})

    assert raw.post("/api/chats").status_code == 403
    assert raw.post("/api/profiles", json={}).status_code == 403


def test_same_origin_writes_are_accepted_when_deployed(remote, upstream):
    pid = make(remote)
    chat_id = remote.post("/api/chats").json()["id"]

    results = unsafe_calls(remote, chat_id, pid)

    assert all(r.status_code < 400 for r in results.values()), {n: r.status_code for n, r in results.items()}


def test_the_vite_dev_origin_is_accepted_on_profile_routes_only(remote, upstream):
    pid = make(remote)
    chat_id = remote.post("/api/chats").json()["id"]

    results = unsafe_calls(remote, chat_id, pid, **VITE)

    chat_codes = {n: r.status_code for n, r in results.items() if "chat" in n.lower() or n in ("PUT story", "POST messages")}
    profile_codes = {n: r.status_code for n, r in results.items() if n not in chat_codes}
    assert set(chat_codes.values()) == {403}
    assert all(code < 400 for code in profile_codes.values()), profile_codes


def test_reads_stay_open_without_an_origin_when_deployed(remote):
    raw = TestClient(server.app, base_url=HTTPS, headers={"X-Test-User": A})

    assert raw.get("/api/chats").status_code == 200
    assert raw.get("/api/profiles", headers=EVIL).status_code == 200  # reads change nothing
    assert raw.get("/api/chats", headers=EVIL).status_code == 200


def test_local_use_is_unaffected_by_the_origin_check(api):
    server.app.dependency_overrides.pop(auth.current_user)  # the real dependency: the fixed local user
    # Not deployed: the chat routes keep ignoring Origin, as before.
    assert api.post("/api/chats", headers=EVIL).status_code == 201
    # The profile routes have always insisted on a local origin.
    assert api.post("/api/profiles", json={}, headers=EVIL).status_code == 403
